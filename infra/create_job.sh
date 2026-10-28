#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): create or update the Databricks job
#
# Creates the job "calendly_pipeline" from jobs/calendly_pipeline.json, or resets it
# to that definition if it already exists. Run from Azure Cloud Shell after
# configure_databricks.sh (which installs the Databricks CLI).
#
#   bash infra/create_job.sh
# =============================================================================
set -euo pipefail

RG="rg-calendly"
DBW_WORKSPACE="dbw-calendly-kcm"
JOB_FILE="$(cd "$(dirname "$0")/.." && pwd)/jobs/calendly_pipeline.json"
JOB_NAME=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$JOB_FILE")

export PATH="$HOME/.local/bin:$PATH"
if ! command -v databricks >/dev/null 2>&1; then
  echo "Databricks CLI not found; run infra/configure_databricks.sh first." >&2; exit 1
fi
export DATABRICKS_HOST="https://$(az databricks workspace show -n "$DBW_WORKSPACE" -g "$RG" --query workspaceUrl -o tsv)"
export DATABRICKS_AUTH_TYPE="azure-cli"

EXISTING=$(databricks jobs list --name "$JOB_NAME" --output json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['job_id'] if d else '')")
if [[ -n "$EXISTING" ]]; then
  echo "Updating job $JOB_NAME (id $EXISTING)"
  databricks jobs reset --json "{\"job_id\": $EXISTING, \"new_settings\": $(cat "$JOB_FILE")}"
  JOB_ID=$EXISTING
else
  echo "Creating job $JOB_NAME"
  JOB_ID=$(databricks jobs create --json @"$JOB_FILE" --output json | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
fi
echo "Job id: $JOB_ID"
echo "Starting a run now to verify"
databricks jobs run-now "$JOB_ID" --output json | python3 -c "import json,sys; d=json.load(sys.stdin); print('run id', d.get('run_id'), 'state', d.get('state',{}).get('result_state', d.get('state',{}).get('life_cycle_state')))"
echo "Open $DATABRICKS_HOST/#job/$JOB_ID to see the run."
