#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): Azure environment, Phase 1
#
# Creates every resource in Section 10 of the architecture proposal:
#   resource group, data lake (ADLS Gen2) with bronze/silver/gold containers,
#   function host storage, Key Vault, Log Analytics, Application Insights,
#   Function App (Linux Consumption, Python 3.11), Azure Databricks workspace
#   (Premium) and its access connector, plus role assignments and the Function
#   App settings consumed by the code in Phase 2.
#
# Idempotent: each step checks for the resource first, so the script can be
# rerun after a partial failure. Run from Azure Cloud Shell (bash):
#
#   bash infra/create_environment.sh
#
# Optional: export CALENDLY_SIGNING_KEY beforehand to store the real key; when
# it is not set, a placeholder secret is created and replaced later with
#   az keyvault secret set --vault-name kv-calendly-kcm -n calendly-signing-key --value '<key>'
#
# Databricks-internal configuration (secret scope, Unity Catalog storage
# credential, external locations, catalog and schemas) is done afterwards by
# infra/configure_databricks.sh, which needs the workspace created here.
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------
# Names (Section 10 of the proposal)
# ----------------------------------------------------------------------------
LOCATION="westus3"
RG="rg-calendly"
STORAGE="stcalendlykcm"            # ADLS Gen2: bronze, silver, gold, metastore
FUNC_STORAGE="stcalendlyfnkcm"     # Function host storage (no hierarchical namespace)
KEYVAULT="kv-calendly-kcm"
LOG_WORKSPACE="log-calendly-kcm"
APP_INSIGHTS="appi-calendly-kcm"
FUNC_APP="func-calendly-kcm"
DBW_WORKSPACE="dbw-calendly-kcm"
DBW_MANAGED_RG="rg-calendly-dbw-managed"
ACCESS_CONNECTOR="dbac-calendly-kcm"
SPEND_BASE_URL="https://dea-data-bucket.s3.us-east-1.amazonaws.com/calendly_spend_data"
TAGS="project=calendly-marketing-insights owner=kcm"
CONTAINERS="bronze silver gold metastore"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '    exists: %s\n' "$*"; }

az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
MY_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
log "Subscription $SUBSCRIPTION_ID, location $LOCATION"

# ----------------------------------------------------------------------------
# 0. Resource providers (one-time per subscription; no-op when registered)
# ----------------------------------------------------------------------------
log "0. Resource providers"
for ns in Microsoft.Web Microsoft.Databricks Microsoft.OperationalInsights Microsoft.Insights Microsoft.KeyVault; do
  state=$(az provider show -n "$ns" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
  if [[ "$state" != "Registered" ]]; then
    printf '    registering %s\n' "$ns"
    az provider register -n "$ns" --wait --only-show-errors >/dev/null
  else
    skip "$ns"
  fi
done

# ----------------------------------------------------------------------------
# 1. Resource group
# ----------------------------------------------------------------------------
log "1. Resource group $RG"
if az group show -n "$RG" --only-show-errors >/dev/null 2>&1; then skip "$RG"; else
  az group create -n "$RG" -l "$LOCATION" --tags $TAGS --only-show-errors >/dev/null
fi

# ----------------------------------------------------------------------------
# 2. Storage accounts and containers
# ----------------------------------------------------------------------------
log "2. Data lake storage $STORAGE (hierarchical namespace)"
if az storage account show -n "$STORAGE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$STORAGE"; else
  az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --enable-hierarchical-namespace true \
    --min-tls-version TLS1_2 --https-only true --allow-blob-public-access false \
    --tags $TAGS --only-show-errors >/dev/null
fi
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)

# The signed-in user needs a data-plane role to create containers with --auth-mode login.
az role assignment create --assignee-object-id "$MY_OBJECT_ID" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" --only-show-errors >/dev/null 2>&1 || true

for c in $CONTAINERS; do
  if az storage container show -n "$c" --account-name "$STORAGE" --auth-mode login --only-show-errors >/dev/null 2>&1; then
    skip "container $c"
  else
    # Role propagation can take a minute; retry a few times.
    for attempt in 1 2 3 4 5 6; do
      if az storage container create -n "$c" --account-name "$STORAGE" --auth-mode login --only-show-errors >/dev/null 2>&1; then
        break
      fi
      [[ $attempt -eq 6 ]] && { echo "Could not create container $c" >&2; exit 1; }
      sleep 20
    done
  fi
done

log "2b. Function host storage $FUNC_STORAGE"
if az storage account show -n "$FUNC_STORAGE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$FUNC_STORAGE"; else
  az storage account create -n "$FUNC_STORAGE" -g "$RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --https-only true \
    --allow-blob-public-access false --tags $TAGS --only-show-errors >/dev/null
fi

# ----------------------------------------------------------------------------
# 3. Key Vault and secrets
# ----------------------------------------------------------------------------
log "3. Key Vault $KEYVAULT (RBAC)"
if az keyvault show -n "$KEYVAULT" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$KEYVAULT"; else
  if az keyvault list-deleted --query "[?name=='$KEYVAULT']" -o tsv --only-show-errors | grep -q "$KEYVAULT"; then
    log "   recovering soft-deleted vault $KEYVAULT"
    az keyvault recover -n "$KEYVAULT" --only-show-errors >/dev/null
  else
    az keyvault create -n "$KEYVAULT" -g "$RG" -l "$LOCATION" --enable-rbac-authorization true \
      --tags $TAGS --only-show-errors >/dev/null
  fi
fi
KV_ID=$(az keyvault show -n "$KEYVAULT" -g "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$MY_OBJECT_ID" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope "$KV_ID" --only-show-errors >/dev/null 2>&1 || true

# Key Vault-backed Databricks secret scopes are read by the AzureDatabricks service
# principal (application id 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d), which needs
# Key Vault Secrets User on the vault (decision 17).
DBX_SP_OBJECT_ID=$(az ad sp show --id 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d --query id -o tsv 2>/dev/null || true)
if [[ -n "$DBX_SP_OBJECT_ID" ]]; then
  az role assignment create --assignee-object-id "$DBX_SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets User" --scope "$KV_ID" --only-show-errors >/dev/null 2>&1 || true
else
  echo "    warning: AzureDatabricks service principal not found in this tenant; the secret scope will fail until it has Key Vault Secrets User" >&2
fi

set_secret() {  # name value
  for attempt in 1 2 3 4 5 6; do
    if az keyvault secret set --vault-name "$KEYVAULT" -n "$1" --value "$2" --only-show-errors >/dev/null 2>&1; then return 0; fi
    [[ $attempt -eq 6 ]] && { echo "Could not set secret $1" >&2; exit 1; }
    sleep 20
  done
}
if az keyvault secret show --vault-name "$KEYVAULT" -n calendly-signing-key --only-show-errors >/dev/null 2>&1 \
   && [[ -z "${CALENDLY_SIGNING_KEY:-}" ]]; then
  skip "secret calendly-signing-key"
else
  set_secret calendly-signing-key "${CALENDLY_SIGNING_KEY:-pending-from-program}"
  [[ -z "${CALENDLY_SIGNING_KEY:-}" ]] && printf '    placeholder stored; replace it when the program shares the key\n'
fi

# ----------------------------------------------------------------------------
# 4. Log Analytics and Application Insights
# ----------------------------------------------------------------------------
log "4. Log Analytics $LOG_WORKSPACE and Application Insights $APP_INSIGHTS"
if az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$LOG_WORKSPACE"; else
  az monitor log-analytics workspace create -n "$LOG_WORKSPACE" -g "$RG" -l "$LOCATION" \
    --retention-time 30 --tags $TAGS --only-show-errors >/dev/null
fi
LOG_ID=$(az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RG" --query id -o tsv)
if az monitor app-insights component show --app "$APP_INSIGHTS" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$APP_INSIGHTS"; else
  az monitor app-insights component create --app "$APP_INSIGHTS" -g "$RG" -l "$LOCATION" \
    --kind web --application-type web --workspace "$LOG_ID" --tags $TAGS --only-show-errors >/dev/null
fi

# ----------------------------------------------------------------------------
# 5. Function App (Linux Consumption, Python 3.11, system-assigned identity)
# ----------------------------------------------------------------------------
log "5. Function App $FUNC_APP"
if az functionapp show -n "$FUNC_APP" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$FUNC_APP"; else
  az functionapp create -n "$FUNC_APP" -g "$RG" --storage-account "$FUNC_STORAGE" \
    --consumption-plan-location "$LOCATION" --os-type Linux \
    --runtime python --runtime-version 3.11 --functions-version 4 \
    --app-insights "$APP_INSIGHTS" --assign-identity "[system]" \
    --https-only true --tags $TAGS --only-show-errors >/dev/null
fi
FUNC_PRINCIPAL=$(az functionapp identity show -n "$FUNC_APP" -g "$RG" --query principalId -o tsv)
if [[ -z "$FUNC_PRINCIPAL" ]]; then
  FUNC_PRINCIPAL=$(az functionapp identity assign -n "$FUNC_APP" -g "$RG" --query principalId -o tsv)
fi

log "5b. Role assignments for the Function App identity"
for role in "Storage Blob Data Contributor"; do
  az role assignment create --assignee-object-id "$FUNC_PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$role" --scope "$STORAGE_ID" --only-show-errors >/dev/null 2>&1 || true
done
az role assignment create --assignee-object-id "$FUNC_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" --only-show-errors >/dev/null 2>&1 || true

log "5c. Application settings"
az functionapp config appsettings set -n "$FUNC_APP" -g "$RG" --only-show-errors --settings \
  "STORAGE_ACCOUNT_URL=https://${STORAGE}.blob.core.windows.net" \
  "BRONZE_CONTAINER=bronze" \
  "CALENDLY_LANDING_PREFIX=calendly/landing" \
  "SPEND_LANDING_PREFIX=spend/landing" \
  "SPEND_QUARANTINE_PREFIX=spend/quarantine" \
  "SPEND_BASE_URL=${SPEND_BASE_URL}" \
  "SPEND_FETCH_SCHEDULE=0 15,45 10-16 * * *" \
  "SPEND_LOOKBACK_DAYS=35" \
  "VERIFY_SIGNATURE=false" \
  "SIGNATURE_TOLERANCE_SECONDS=300" \
  "CALENDLY_SIGNING_KEY=@Microsoft.KeyVault(VaultName=${KEYVAULT};SecretName=calendly-signing-key)" \
  "SCM_DO_BUILD_DURING_DEPLOYMENT=true" \
  "ENABLE_ORYX_BUILD=true" >/dev/null

# ----------------------------------------------------------------------------
# 6. Azure Databricks workspace (Premium) and access connector
# ----------------------------------------------------------------------------
log "6. Databricks workspace $DBW_WORKSPACE (Premium); this step takes several minutes"
if az databricks workspace show -n "$DBW_WORKSPACE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$DBW_WORKSPACE"; else
  az databricks workspace create -n "$DBW_WORKSPACE" -g "$RG" -l "$LOCATION" --sku premium \
    --managed-resource-group "$DBW_MANAGED_RG" --tags $TAGS --only-show-errors >/dev/null
fi
DBW_URL=$(az databricks workspace show -n "$DBW_WORKSPACE" -g "$RG" --query workspaceUrl -o tsv)

log "6b. Access connector $ACCESS_CONNECTOR (managed identity for Unity Catalog storage access)"
if az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$ACCESS_CONNECTOR"; else
  az databricks access-connector create -n "$ACCESS_CONNECTOR" -g "$RG" -l "$LOCATION" \
    --identity-type SystemAssigned --tags $TAGS --only-show-errors >/dev/null
fi
DBAC_PRINCIPAL=$(az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" --query identity.principalId -o tsv)
DBAC_ID=$(az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" --query id -o tsv)
for role in "Storage Blob Data Contributor" "Storage Queue Data Contributor"; do
  az role assignment create --assignee-object-id "$DBAC_PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$role" --scope "$STORAGE_ID" --only-show-errors >/dev/null 2>&1 || true
done

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
log "Done. Resources in $RG:"
az resource list -g "$RG" --query "sort_by([].{name:name, type:type}, &name)" -o table

cat <<EOF

Next steps
  1. bash infra/verify_environment.sh
  2. bash infra/configure_databricks.sh      (secret scope, Unity Catalog objects)
  3. Record the values below in docs/phase1_environment.md:
       Databricks workspace URL : https://${DBW_URL}
       Access connector id      : ${DBAC_ID}
       Function App             : https://${FUNC_APP}.azurewebsites.net
EOF
