# Run BullRun locally: Flask API on :5000, Spade agent on :8080, React app on :5173.
# Uses the real keys in agent_service\.env and the real Firestore (your gcloud login).
#
#   .\dev.ps1 -Setup   # first time only: installs server + client deps, signs gcloud in for Firestore
#   .\dev.ps1          # starts all three in their own windows; code changes reload automatically
param([switch]$Setup)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$envFile = Join-Path $root "agent_service\.env"
$python = Join-Path $root "agent_service\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No venv at agent_service\.venv. Create it first (see agent_service\README.md)." }

function Read-DotEnv {
    $vars = @{}
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$') { $vars[$Matches[1]] = $Matches[2].Trim().Trim('"') }
        }
    }
    return $vars
}

function Add-DotEnv($name, $value) {
    Add-Content -Path $envFile -Value "$name=$value"
    Write-Host "  added $name to agent_service\.env"
}

if ($Setup) {
    Write-Host "Installing server deps into the agent venv..."
    & $python -m pip install -q -r (Join-Path $root "agent_service\requirements.txt") flask flask-cors snaptrade-python-sdk pyjwt
    Write-Host "Installing client deps..."
    Push-Location (Join-Path $root "client"); npm install; Pop-Location
    Write-Host "Signing gcloud in so local code can reach Firestore..."
    gcloud auth application-default login
    gcloud auth application-default set-quota-project bullrunai-rishabh
}

# Settings both backends need; asked for once, then kept in .env (git-ignored).
$vars = Read-DotEnv
if (-not $vars["PROJECT_ID"]) { Add-DotEnv "PROJECT_ID" "bullrunai-rishabh" }
if (-not $vars["FIRESTORE_DATABASE"]) { Add-DotEnv "FIRESTORE_DATABASE" "(default)" }
if (-not $vars["GOOGLE_CLIENT_ID"]) {
    $id = Read-Host "OAuth Client ID (ends in .apps.googleusercontent.com; in Cloud Shell: cat ~/BullRunAI/deploy/.deploy.env)"
    Add-DotEnv "GOOGLE_CLIENT_ID" $id
}
if (-not $vars["SESSION_SECRET"]) {
    Add-DotEnv "SESSION_SECRET" (-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }))
}
$vars = Read-DotEnv

# Child windows inherit these.
foreach ($k in $vars.Keys) { Set-Item -Path "Env:$k" -Value $vars[$k] }
$env:AUTH_DISABLED = "false"
$env:TOOLS_MODE = "local"
$env:VITE_APP_API_URL = "http://localhost:5000"
$env:VITE_AGENT_API_URL = "http://localhost:8080"
$env:VITE_APP_GOOGLE_CLIENT_ID = $vars["GOOGLE_CLIENT_ID"]

$server = Join-Path $root "server"
$agent = Join-Path $root "agent_service"
$client = Join-Path $root "client"
Start-Process powershell -WorkingDirectory $server -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='BullRun API :5000'; & '$python' app.py"
Start-Process powershell -WorkingDirectory $agent -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Spade agent :8080'; & '$python' -m uvicorn bullrun_agent.api:app --port 8080 --reload"
Start-Process powershell -WorkingDirectory $client -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='BullRun client :5173'; npm run dev"

Write-Host ""
Write-Host "Starting... open http://localhost:5173 in ~15s. Close the three windows to stop."
