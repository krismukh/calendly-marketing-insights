#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): deploy the Function App from Cloud Shell
#
# Zips src/ (the Functions project root) and deploys it to func-calendly-kcm with a
# remote build, then prints the health URL and the webhook URL with its key.
#
#   bash infra/deploy_function.sh
#
# Phase 4 adds the same deployment to GitHub Actions; this script remains the manual path.
# =============================================================================
set -euo pipefail

RG="rg-calendly"
FUNC_APP="func-calendly-kcm"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/src"
ZIP="/tmp/${FUNC_APP}-$(date +%Y%m%d%H%M%S).zip"

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

log "Packaging $SRC_DIR"
( cd "$SRC_DIR" && zip -q -r "$ZIP" . -x '.venv/*' '__pycache__/*' '*/__pycache__/*' '*.pyc' 'local.settings.json' 'local.settings.json.example' )
ls -lh "$ZIP"

log "Deploying to $FUNC_APP (remote build; 2 to 4 minutes)"
az functionapp deployment source config-zip -n "$FUNC_APP" -g "$RG" --src "$ZIP" --build-remote true --only-show-errors >/dev/null
rm -f "$ZIP"

log "Waiting for the host to restart"
sleep 30
HOST=$(az functionapp show -n "$FUNC_APP" -g "$RG" --query defaultHostName -o tsv)
for attempt in 1 2 3 4 5 6; do
  if curl -fsS "https://${HOST}/api/health" >/tmp/health.json 2>/dev/null; then break; fi
  [[ $attempt -eq 6 ]] && { echo "health endpoint not responding" >&2; exit 1; }
  sleep 20
done
printf '    health: '; cat /tmp/health.json; echo

log "Functions deployed"
az functionapp function list -n "$FUNC_APP" -g "$RG" --query "[].{name:name, trigger:config.bindings[0].type}" -o table

KEY=$(az functionapp keys list -n "$FUNC_APP" -g "$RG" --query functionKeys.default -o tsv)
cat <<EOF

Webhook URL (share with the program for the subscription; keep the key private):
  https://${HOST}/api/calendly?code=${KEY}

Manual spend fetch:
  https://${HOST}/api/spend/fetch?code=${KEY}

Health:
  https://${HOST}/api/health

Add to .env on the workstation:
  FUNCTION_URL=https://${HOST}
  FUNCTION_KEY=${KEY}
EOF
