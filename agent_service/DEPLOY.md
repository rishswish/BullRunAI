# Deploying BullRun 2.0 to Google Cloud

Commands are for **Windows PowerShell** (use `\` instead of `` ` `` for line breaks on mac/linux).
Budget: with `min-instances=0` and Gemini Flash, a demo deployment typically costs a few dollars a month.
Set a billing budget alert anyway (Billing → Budgets & alerts).

## 0. What you need

| Item | Where | Free? |
|---|---|---|
| GCP project with billing enabled | console.cloud.google.com | free credits for new accounts |
| `gcloud` CLI | cloud.google.com/sdk/docs/install | yes |
| Gemini API key | aistudio.google.com/apikey | free tier |
| Polygon.io key (optional; demo data otherwise) | polygon.io | free tier, 5 req/min |
| LangSmith key (optional, tracing) | smith.langchain.com | free tier |
| Google OAuth client ID (for login) | APIs & Services → Credentials | yes |

## 1. Set up the project

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
$PROJECT = gcloud config get-value project
$REGION = "us-central1"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
  secretmanager.googleapis.com storage.googleapis.com firestore.googleapis.com

gcloud artifacts repositories create br --repository-format=docker --location=$REGION
```

## 2. Secrets (never put keys in env files that get committed)

```powershell
"YOUR_GEMINI_KEY"  | gcloud secrets create google-api-key  --data-file=-
"YOUR_POLYGON_KEY" | gcloud secrets create polygon-api-key --data-file=-
"YOUR_LANGSMITH_KEY" | gcloud secrets create langsmith-api-key --data-file=-
# Firestore service-account JSON (same one the Flask server uses):
gcloud secrets create firebase-service-account --data-file=path\to\service-account.json
```

No Polygon or LangSmith key yet? Create the secret with the text `none` and set the
matching env var empty later. Without `POLYGON_API_KEY` the agent uses demo market data.

## 3. Runtime service account

```powershell
gcloud iam service-accounts create br-agent-runtime --display-name "BullRun agent runtime"
$SA = "br-agent-runtime@$PROJECT.iam.gserviceaccount.com"
foreach ($role in "roles/secretmanager.secretAccessor","roles/storage.objectViewer","roles/datastore.user") {
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role=$role
}
# Let Cloud Build deploy as that account:
$CB = "$(gcloud projects describe $PROJECT --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$CB" --role=roles/run.admin
gcloud iam service-accounts add-iam-policy-binding $SA --member="serviceAccount:$CB" --role=roles/iam.serviceAccountUser
```

## 4. Build the filings index and upload it

```powershell
cd agent_service
.venv\Scripts\activate
python -m bullrun_agent.rag.ingest --tickers NVDA AAPL MSFT TSLA AMZN GOOGL META AMD
gcloud storage buckets create gs://$PROJECT-bullrun-rag --location=$REGION
python -m bullrun_agent.rag.ingest --tickers NVDA AAPL MSFT TSLA AMZN GOOGL META AMD --upload gs://$PROJECT-bullrun-rag/filings_index
cd ..
```

(The second command rebuilds and uploads; if you already built, upload with
`gcloud storage cp agent_service\data\filings_index\* gs://$PROJECT-bullrun-rag/filings_index/`.)

## 5. Deploy the MCP server + agent API

From the **repo root**:

```powershell
gcloud builds submit --config agent_service/cloudbuild.yaml `
  --substitutions="SHORT_SHA=v1,_INDEX_GCS_URI=gs://$PROJECT-bullrun-rag/filings_index,_GOOGLE_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com,_CLIENT_ORIGIN=https://YOUR_FRONTEND_URL"
```

This runs the unit tests, builds one image, and deploys two Cloud Run services:
`br-mcp` (MCP server) and `br-agent` (FastAPI, `TOOLS_MODE=mcp`).

Check it:

```powershell
$AGENT = gcloud run services describe br-agent --region=$REGION --format='value(status.url)'
curl.exe "$AGENT/health"
```

`/health` should show `"provider": "gemini"` and your filings index tickers.

## 6. Durable chat memory (optional but recommended)

Cloud Run instances are ephemeral, so in-memory threads vanish on scale-down. Point the
agent at Postgres (a free Neon/Supabase database is fine, or Cloud SQL):

```powershell
"postgresql://USER:PASS@HOST/DB?sslmode=require" | gcloud secrets create checkpoint-db-url --data-file=-
gcloud run services update br-agent --region=$REGION --update-secrets=CHECKPOINT_DB_URL=checkpoint-db-url:latest
```

## 7. Frontend + existing backend

1. **Client** (`client/`): add `VITE_AGENT_API_URL=<br-agent URL>` next to the existing
   `VITE_APP_API_URL` and `VITE_APP_GOOGLE_CLIENT_ID`, then deploy as before (Vercel or
   `client/cloudbuild.yaml`). On Vercel: Project → Settings → Environment Variables.
2. **Flask server** (`server/`): `server/cloudbuild.yaml` hard-codes the original
   `br-deploy@br-prod-475122` service account; change it to your own before deploying.
   It expects a Firestore database named `br-prod-db` (create it in Firestore → Create database).
3. **OAuth**: in the OAuth client, add your frontend URL under *Authorized JavaScript origins*.

## 8. CI/CD

* **Cloud Build trigger**: Cloud Build → Triggers → Connect repository → push to `main`,
  included files `agent_service/**`, config `agent_service/cloudbuild.yaml`, with the same
  substitutions as step 5 (`SHORT_SHA` is filled automatically by triggers).
* **GitHub Actions** (`.github/workflows/agent-ci.yml`): lint + unit tests on every PR;
  add a `GOOGLE_API_KEY` repo secret to enable the real-model eval gate.

## 9. Locking down the MCP server (production hardening)

`br-mcp` is public in this setup because it only serves public market data. To make it
private: redeploy with `--no-allow-unauthenticated`, grant `roles/run.invoker` to the
runtime service account, and have the agent attach a Google-signed ID token
(`google.oauth2.id_token.fetch_id_token`) as an `Authorization` header in the
`MultiServerMCPClient` connection (`"headers": {...}`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` shows `"filings_index": null` | `INDEX_GCS_URI` wrong or SA lacks `storage.objectViewer` |
| 401 from `/api/agent/chat` | `GOOGLE_CLIENT_ID` on br-agent must match the client's OAuth client id |
| CORS error in browser | `_CLIENT_ORIGIN` must exactly match the frontend origin (no trailing slash) |
| Gemini 429 | free-tier rate limit; lower eval `--concurrency` or add billing |
| Tool says `market data unavailable` | Polygon free tier allows 5 req/min; results are cached 60 s |
