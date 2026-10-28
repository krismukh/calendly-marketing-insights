#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): Azure Monitor alert for the Function App
#
# Creates an action group that e-mails the operator and one metric alert that fires
# when the Function App returns any HTTP 5xx in a 5-minute window (receiver landing
# failures, fetcher crashes). Databricks job failures e-mail directly from the job.
#
#   bash infra/create_monitoring.sh
# =============================================================================
set -euo pipefail

RG="rg-calendly"
FUNC_APP="func-calendly-kcm"
ACTION_GROUP="ag-calendly"
EMAIL="${ALERT_EMAIL:-krismukh@hotmail.com}"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '    exists: %s\n' "$*"; }

log "Action group $ACTION_GROUP -> $EMAIL"
if az monitor action-group show -n "$ACTION_GROUP" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$ACTION_GROUP"; else
  az monitor action-group create -n "$ACTION_GROUP" -g "$RG" --short-name calendly \
    --action email operator "$EMAIL" --only-show-errors >/dev/null
fi
AG_ID=$(az monitor action-group show -n "$ACTION_GROUP" -g "$RG" --query id -o tsv)
FUNC_ID=$(az functionapp show -n "$FUNC_APP" -g "$RG" --query id -o tsv)

log "Alert alr-calendly-failures (HTTP 5xx > 0 over 5 minutes)"
if az monitor metrics alert show -n alr-calendly-failures -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "alr-calendly-failures"; else
  az monitor metrics alert create -n alr-calendly-failures -g "$RG" --scopes "$FUNC_ID" \
    --condition "total Http5xx > 0" --window-size 5m --evaluation-frequency 5m --severity 2 \
    --description "Calendly receiver or spend fetcher returned a server error" \
    --action "$AG_ID" --only-show-errors >/dev/null
fi
az monitor metrics alert list -g "$RG" --query "[].{name:name, enabled:enabled, severity:severity}" -o table
echo "Confirm the action-group e-mail subscription from the message Azure sends to $EMAIL."
