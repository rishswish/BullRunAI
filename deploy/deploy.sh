#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# BullRun 2.0: one-shot deploy of the full stack to Google Cloud.
#
# Run it from Google Cloud Shell (https://shell.cloud.google.com), where gcloud
# is already signed in:
#
#   git clone https://github.com/rishswish/BullRunAI.git && cd BullRunAI
#   gcloud config set project YOUR_PROJECT_ID
#   bash deploy/deploy.sh
#
# It is safe to re-run: every step checks what already exists. API keys are
# typed at hidden prompts and go straight into Secret Manager; they are never
# written to disk or echoed.
#
# What it deploys (all in one region):
#   br-client   React app                       (Cloud Run service)
#   br-server   Flask API                       (Cloud Run service)
#   br-agent    Spade LangGraph agent, SSE API  (Cloud Run service)
#   br-mcp      BullRun MCP server              (Cloud Run service)
#   br-global-agent / br-personal-agent  report generators (Cloud Run jobs + Cloud Scheduler)
#   br-rag-ingest   builds the SEC filings index into Cloud Storage (Cloud Run job)
#   Firestore (default) database, Secret Manager secrets, one runtime service account
#
# Options (environment variables):
#   REGION=us-central1     LLM_MODEL=gemini-2.5-flash     ROUTER_MODEL=gemini-2.5-flash-lite
#   MIN_INSTANCES=0        set to 1 on demo day to avoid cold starts (small hourly cost)
#   RESET_SECRETS=1        re-prompt for every API key
#   SKIP_BUILD=1           redeploy using the last built images
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT=$(pwd)

REGION=${REGION:-us-central1}
LLM_MODEL=${LLM_MODEL:-gemini-2.5-flash}
ROUTER_MODEL=${ROUTER_MODEL:-gemini-2.5-flash-lite}
MIN_INSTANCES=${MIN_INSTANCES:-0}
FIRESTORE_DB="(default)"
AR_REPO=br
SA_NAME=br-runtime
STATE_FILE="$REPO_ROOT/deploy/.deploy.env"
RAG_TICKERS=${RAG_TICKERS:-"NVDA AAPL MSFT TSLA AMZN GOOGL META AMD"}

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m  x %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
bold "0/9  Checking project"
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)
[[ -n "$PROJECT_ID" ]] || die "No project set. Run: gcloud config set project YOUR_PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
ACCOUNT=$(gcloud config get-value account 2>/dev/null)
info "project=$PROJECT_ID ($PROJECT_NUMBER)  region=$REGION  account=$ACCOUNT"

BILLING=$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || echo "")
if [[ "$BILLING" != "True" ]]; then
  die "Billing is not enabled on $PROJECT_ID. Link a billing account (free trial credits work):
     https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID
     then re-run this script."
fi

# Cloud Run gives every service a predictable URL: https://SERVICE-PROJECTNUMBER.REGION.run.app
url_for() { echo "https://$1-$PROJECT_NUMBER.$REGION.run.app"; }
CLIENT_URL=$(url_for br-client)
SERVER_URL=$(url_for br-server)
AGENT_URL=$(url_for br-agent)
MCP_URL=$(url_for br-mcp)

# shellcheck disable=SC1090
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"

# ---------------------------------------------------------------------------
bold "1/9  Enabling Google Cloud APIs (first run takes ~1 min)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com cloudscheduler.googleapis.com \
  iam.googleapis.com storage.googleapis.com --quiet

# ---------------------------------------------------------------------------
bold "2/9  Google sign-in (OAuth client)"
if [[ -z "${OAUTH_CLIENT_ID:-}" ]]; then
  cat <<EOF
  The app's "Sign in with Google" needs an OAuth client ID. Create it once:

   1. Open https://console.cloud.google.com/auth/overview?project=$PROJECT_ID
      -> Get started. App name: BullRunAI, support email: yours,
         Audience: External, contact email: yours -> Create.
   2. Audience -> click "Publish app" (otherwise only listed test users can sign in).
   3. Clients -> Create client -> Application type: Web application
      Authorized JavaScript origins (add all three):
        $CLIENT_URL
        http://localhost:5173
        http://localhost
      -> Create, then copy the Client ID (ends in .apps.googleusercontent.com).

EOF
  read -rp "  Paste the OAuth Client ID: " OAUTH_CLIENT_ID
  [[ "$OAUTH_CLIENT_ID" == *.apps.googleusercontent.com ]] || die "That doesn't look like an OAuth client ID."
  echo "OAUTH_CLIENT_ID=$OAUTH_CLIENT_ID" > "$STATE_FILE"
else
  info "using saved client id ${OAUTH_CLIENT_ID%%-*}-…  (delete deploy/.deploy.env to change it)"
fi

# ---------------------------------------------------------------------------
bold "3/9  Secrets (keys are hidden as you type; press Enter to skip optional ones)"
declare -A HAVE
ensure_secret() {  # name, label, required(yes/no)
  local name=$1 label=$2 required=$3 val=""
  if gcloud secrets describe "$name" >/dev/null 2>&1 && [[ -z "${RESET_SECRETS:-}" ]]; then
    info "$name: already stored"; HAVE[$name]=1; return
  fi
  read -rsp "  $label: " val; echo
  if [[ -z "$val" ]]; then
    [[ "$required" == yes ]] && die "$name is required."
    info "$name: skipped"; return
  fi
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$val" | gcloud secrets versions add "$name" --data-file=- --quiet >/dev/null
  else
    printf '%s' "$val" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic --quiet >/dev/null
  fi
  info "$name: saved"; HAVE[$name]=1
}
ensure_secret google-api-key        "Gemini API key (required, aistudio.google.com/apikey)" yes
ensure_secret polygon-api-key       "Polygon.io API key (recommended, live prices + ticker pages)" no
ensure_secret snaptrade-consumer-key "SnapTrade consumer key (optional, brokerage linking)" no
ensure_secret snaptrade-client-id   "SnapTrade client id (optional)" no
ensure_secret langsmith-api-key     "LangSmith API key (optional, agent tracing)" no

# Build the --set-secrets lists from what exists.
secrets_flag() {  # pairs: ENV_NAME=secret-name ...
  local out="" pair
  for pair in "$@"; do
    [[ -n "${HAVE[${pair#*=}]:-}" ]] && out+="${out:+,}${pair}:latest"
  done
  echo "$out"
}
AGENT_SECRETS=$(secrets_flag GOOGLE_API_KEY=google-api-key POLYGON_API_KEY=polygon-api-key \
  LANGSMITH_API_KEY=langsmith-api-key SNAPTRADE_CONSUMER_KEY=snaptrade-consumer-key SNAPTRADE_CLIENT_ID=snaptrade-client-id)
MCP_SECRETS=$(secrets_flag GOOGLE_API_KEY=google-api-key POLYGON_API_KEY=polygon-api-key)
SERVER_SECRETS=$(secrets_flag GOOGLE_API_KEY=google-api-key POLYGON_API_KEY=polygon-api-key \
  SNAPTRADE_CONSUMER_KEY=snaptrade-consumer-key SNAPTRADE_CLIENT_ID=snaptrade-client-id)
TRACING=false; [[ -n "${HAVE[langsmith-api-key]:-}" ]] && TRACING=true

# ---------------------------------------------------------------------------
bold "4/9  Service account, Firestore, storage, image registry"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="BullRun runtime" --quiet
  sleep 10  # IAM propagation
fi
for role in roles/datastore.user roles/secretmanager.secretAccessor roles/run.invoker roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" \
    --role="$role" --condition=None --quiet >/dev/null
done
# New projects build with the Compute Engine default service account; make sure it can push images and write logs.
BUILD_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" \
    --role="$role" --condition=None --quiet >/dev/null 2>&1 || warn "could not grant $role to $BUILD_SA"
done
info "service account: $SA_EMAIL"

if ! gcloud firestore databases describe --database="$FIRESTORE_DB" >/dev/null 2>&1; then
  gcloud firestore databases create --database="$FIRESTORE_DB" --location="$REGION" --type=firestore-native --quiet
fi
info "firestore: $FIRESTORE_DB"

BUCKET="gs://$PROJECT_ID-bullrun-rag"
if ! gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "$BUCKET" --location="$REGION" --uniform-bucket-level-access --quiet
fi
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$SA_EMAIL" \
  --role=roles/storage.objectAdmin --quiet >/dev/null
INDEX_URI="$BUCKET/filings_index"
info "rag bucket: $BUCKET"

if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION" --quiet
fi
IMG="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO"
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" --quiet \
  --policy=<(printf '%s' '[{"name":"keep-latest-2","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":2}},{"name":"delete-old","action":{"type":"Delete"},"condition":{"olderThan":"604800s"}}]') \
  >/dev/null 2>&1 || warn "could not set image cleanup policy (optional)"

# ---------------------------------------------------------------------------
bold "5/9  Building container images with Cloud Build (~10-15 min the first time)"
if [[ -z "${SKIP_BUILD:-}" ]]; then
  build() {  # dir image
    info "building $2 ..."
    gcloud builds submit "$1" --tag="$IMG/$2:latest" --quiet --suppress-logs \
      || die "Build of $2 failed. Open https://console.cloud.google.com/cloud-build/builds?project=$PROJECT_ID for logs."
  }
  build agent_service br-agent
  build server br-server
  build global_report_agent br-global-agent
  build personal_report_agent br-personal-agent
  info "building br-client ..."
  gcloud builds submit client --config=deploy/client-build.yaml --quiet --suppress-logs \
    --substitutions="_IMAGE=$IMG/br-client:latest,_VITE_APP_API_URL=$SERVER_URL,_VITE_APP_GOOGLE_CLIENT_ID=$OAUTH_CLIENT_ID,_VITE_AGENT_API_URL=$AGENT_URL" \
    || die "Client build failed. See https://console.cloud.google.com/cloud-build/builds?project=$PROJECT_ID"
else
  info "SKIP_BUILD set: reusing existing images"
fi

COMMON=(--region="$REGION" --service-account="$SA_EMAIL" --quiet)

# ---------------------------------------------------------------------------
bold "6/9  Starting the SEC filings ingest job (runs in the background)"
gcloud run jobs deploy br-rag-ingest --image="$IMG/br-agent:latest" "${COMMON[@]}" \
  --command=python --args="-m,bullrun_agent.rag.ingest,--per-ticker,2,--upload,$INDEX_URI,--tickers,${RAG_TICKERS// /,}" \
  --set-env-vars="^;^EMBEDDING_PROVIDER=gemini;SEC_USER_AGENT=BullRunAI $ACCOUNT;INDEX_DIR=/tmp/filings_index" \
  --set-secrets="GOOGLE_API_KEY=google-api-key:latest" \
  --memory=2Gi --cpu=1 --task-timeout=3600 --max-retries=1 >/dev/null
gcloud run jobs execute br-rag-ingest --region="$REGION" --async --quiet >/dev/null
info "ingest started; Spade's filings search goes live once it finishes (~5-10 min)"

# ---------------------------------------------------------------------------
bold "7/9  Deploying services"
info "br-mcp ..."
gcloud run deploy br-mcp --image="$IMG/br-agent:latest" "${COMMON[@]}" \
  --command=python --args="-m,bullrun_agent.mcp_server,--http" \
  --set-env-vars="^;^EMBEDDING_PROVIDER=gemini;INDEX_GCS_URI=$INDEX_URI;INDEX_DIR=/tmp/filings_index" \
  --set-secrets="$MCP_SECRETS" --memory=1Gi --min-instances=0 --max-instances=2 \
  --allow-unauthenticated >/dev/null

info "br-agent ..."
# max-instances=1 because chat memory is in-process; set CHECKPOINT_DB_URL (Postgres) to scale out.
gcloud run deploy br-agent --image="$IMG/br-agent:latest" "${COMMON[@]}" \
  --set-env-vars="^;^LLM_PROVIDER=gemini;LLM_MODEL=$LLM_MODEL;ROUTER_MODEL=$ROUTER_MODEL;EMBEDDING_PROVIDER=gemini;TOOLS_MODE=mcp;MCP_SERVER_URL=$MCP_URL/mcp;PROJECT_ID=$PROJECT_ID;FIRESTORE_DATABASE=$FIRESTORE_DB;GOOGLE_CLIENT_ID=$OAUTH_CLIENT_ID;CORS_ORIGINS=$CLIENT_URL,http://localhost:5173;INDEX_GCS_URI=$INDEX_URI;INDEX_DIR=/tmp/filings_index;LANGSMITH_TRACING=$TRACING;LANGSMITH_PROJECT=bullrun-agent" \
  --set-secrets="$AGENT_SECRETS" --memory=1Gi --cpu=1 --timeout=300 --concurrency=40 \
  --min-instances="$MIN_INSTANCES" --max-instances=1 --cpu-boost --allow-unauthenticated >/dev/null

info "br-server ..."
gcloud run deploy br-server --image="$IMG/br-server:latest" "${COMMON[@]}" \
  --set-env-vars="^;^PROJECT_ID=$PROJECT_ID;FIRESTORE_DATABASE=$FIRESTORE_DB;GOOGLE_CLIENT_ID=$OAUTH_CLIENT_ID;SNAPTRADE_REDIRECT_BASE=$CLIENT_URL/portfolio" \
  --set-secrets="$SERVER_SECRETS" --memory=1Gi --timeout=300 --min-instances="$MIN_INSTANCES" --max-instances=2 \
  --allow-unauthenticated >/dev/null

info "br-client ..."
gcloud run deploy br-client --image="$IMG/br-client:latest" "${COMMON[@]}" \
  --port=8080 --memory=512Mi --min-instances=0 --max-instances=2 --allow-unauthenticated >/dev/null

# Confirm the predicted URLs match what Cloud Run assigned.
for svc in br-client br-server br-agent br-mcp; do
  if ! gcloud run services describe "$svc" --region="$REGION" --format=json 2>/dev/null | grep -q "$(url_for "$svc")"; then
    warn "$svc is not reachable at $(url_for "$svc"); run: gcloud run services describe $svc --region=$REGION"
  fi
done

# ---------------------------------------------------------------------------
bold "8/9  Report jobs + schedules"
JOB_ENV="PROJECT_ID=$PROJECT_ID,FIRESTORE_DATABASE=$FIRESTORE_DB"
gcloud run jobs deploy br-global-agent --image="$IMG/br-global-agent:latest" "${COMMON[@]}" \
  --set-env-vars="$JOB_ENV" --set-secrets="GOOGLE_API_KEY=google-api-key:latest" \
  --memory=1Gi --task-timeout=900 --max-retries=1 >/dev/null
gcloud run jobs deploy br-personal-agent --image="$IMG/br-personal-agent:latest" "${COMMON[@]}" \
  --set-env-vars="$JOB_ENV" --set-secrets="$SERVER_SECRETS" \
  --memory=1Gi --task-timeout=3600 --max-retries=1 >/dev/null

schedule() {  # name job cron
  local uri="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$2:run"
  local verb=create
  gcloud scheduler jobs describe "$1" --location="$REGION" >/dev/null 2>&1 && verb=update
  gcloud scheduler jobs "$verb" http "$1" --location="$REGION" --schedule="$3" --time-zone="America/New_York" \
    --uri="$uri" --http-method=POST --oauth-service-account-email="$SA_EMAIL" --quiet >/dev/null
  info "$1: '$3' (New York time)"
}
schedule br-global-report br-global-agent "0 7-19/2 * * 1-5"
schedule br-personal-report br-personal-agent "30 6 * * 1-5"

info "generating the first market report now (1-3 min) so the dashboard isn't empty ..."
gcloud run jobs execute br-global-agent --region="$REGION" --wait --quiet >/dev/null \
  || warn "first report failed; check logs: gcloud run jobs executions list --job=br-global-agent --region=$REGION"

# ---------------------------------------------------------------------------
bold "9/9  Health checks"
check() {  # label url
  if curl -fsS --max-time 90 -o /dev/null "$2"; then info "$1 OK"; else warn "$1 not responding yet: $2"; fi
}
check br-server "$SERVER_URL/api/health"
check br-agent "$AGENT_URL/health"
check br-client "$CLIENT_URL"

cat <<EOF

  Done. Open the app:  $CLIENT_URL

  Agent API health:    $AGENT_URL/health
  MCP endpoint:        $MCP_URL/mcp
  Filings ingest:      gcloud run jobs executions list --job=br-rag-ingest --region=$REGION
  Logs:                https://console.cloud.google.com/run?project=$PROJECT_ID

  Demo day: re-run with MIN_INSTANCES=1 SKIP_BUILD=1 bash deploy/deploy.sh to avoid cold starts.
EOF
