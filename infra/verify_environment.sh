#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): verify the Phase 1 environment
#
# Read-only. Prints the state of every resource created by create_environment.sh
# so the output can be pasted into docs/phase1_environment.md.
#
#   bash infra/verify_environment.sh
# =============================================================================
set -uo pipefail

RG="rg-calendly"
STORAGE="stcalendlykcm"
FUNC_STORAGE="stcalendlyfnkcm"
KEYVAULT="kv-calendly-kcm"
LOG_WORKSPACE="log-calendly-kcm"
APP_INSIGHTS="appi-calendly-kcm"
FUNC_APP="func-calendly-kcm"
DBW_WORKSPACE="dbw-calendly-kcm"
ACCESS_CONNECTOR="dbac-calendly-kcm"

hr() { printf '\n== %s ==\n' "$*"; }

hr "Resources in $RG"
az resource list -g "$RG" --query "sort_by([].{name:name, type:type, location:location}, &name)" -o table

hr "Data lake $STORAGE"
az storage account show -n "$STORAGE" -g "$RG" \
  --query "{hns:isHnsEnabled, tls:minimumTlsVersion, httpsOnly:enableHttpsTrafficOnly, publicBlobAccess:allowBlobPublicAccess, encryption:encryption.services.blob.enabled}" -o table
az storage container list --account-name "$STORAGE" --auth-mode login --query "[].name" -o tsv | sed 's/^/    container: /'

hr "Function host storage $FUNC_STORAGE"
az storage account show -n "$FUNC_STORAGE" -g "$RG" --query "{hns:isHnsEnabled, tls:minimumTlsVersion}" -o table

hr "Key Vault $KEYVAULT"
az keyvault show -n "$KEYVAULT" -g "$RG" --query "{rbac:properties.enableRbacAuthorization, softDelete:properties.enableSoftDelete}" -o table
az keyvault secret list --vault-name "$KEYVAULT" --query "[].{secret:name, enabled:attributes.enabled, updated:attributes.updated}" -o table

hr "Monitoring"
az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RG" --query "{name:name, retentionDays:retentionInDays, state:provisioningState}" -o table
az monitor app-insights component show --app "$APP_INSIGHTS" -g "$RG" --query "{name:name, kind:kind, workspace:workspaceResourceId}" -o table

hr "Function App $FUNC_APP"
az functionapp show -n "$FUNC_APP" -g "$RG" \
  --query "{state:state, host:defaultHostName, runtime:siteConfig.linuxFxVersion, httpsOnly:httpsOnly, identity:identity.principalId}" -o table
FUNC_PRINCIPAL=$(az functionapp identity show -n "$FUNC_APP" -g "$RG" --query principalId -o tsv 2>/dev/null)
if [[ -n "$FUNC_PRINCIPAL" ]]; then
  printf '    roles held by the Function App identity:\n'
  az role assignment list --assignee "$FUNC_PRINCIPAL" --all --query "[].{role:roleDefinitionName, scope:scope}" -o table | sed 's/^/    /'
fi
printf '    application settings (names only):\n'
az functionapp config appsettings list -n "$FUNC_APP" -g "$RG" --query "[].name" -o tsv | sort | sed 's/^/      /'
printf '    Key Vault reference status:\n'
az rest --method get \
  --url "https://management.azure.com$(az functionapp show -n "$FUNC_APP" -g "$RG" --query id -o tsv)/config/configreferences/appsettings?api-version=2022-03-01" \
  --query "value[].{setting:name, status:properties.status}" -o table 2>/dev/null | sed 's/^/      /' \
  || echo "      (reference status not available yet)"

hr "Databricks workspace $DBW_WORKSPACE"
az databricks workspace show -n "$DBW_WORKSPACE" -g "$RG" \
  --query "{state:provisioningState, sku:sku.name, url:workspaceUrl, managedRg:managedResourceGroupId}" -o table

hr "Access connector $ACCESS_CONNECTOR"
az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" \
  --query "{state:provisioningState, principalId:identity.principalId, id:id}" -o table
DBAC_PRINCIPAL=$(az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" --query identity.principalId -o tsv 2>/dev/null)
if [[ -n "$DBAC_PRINCIPAL" ]]; then
  printf '    roles held by the access connector identity:\n'
  az role assignment list --assignee "$DBAC_PRINCIPAL" --all --query "[].{role:roleDefinitionName, scope:scope}" -o table | sed 's/^/    /'
fi

hr "Checklist"
cat <<'EOF'
  [ ] 9 resources listed (2 storage accounts, Key Vault, Log Analytics, Application Insights,
      App Service plan, Function App, Databricks workspace, access connector)
  [ ] containers bronze, silver, gold, metastore present; hns true; httpsOnly true
  [ ] secret calendly-signing-key present (placeholder until the program shares the key)
  [ ] Function App state Running; identity holds Storage Blob Data Contributor and Key Vault Secrets User
  [ ] Key Vault reference CALENDLY_SIGNING_KEY shows Resolved (may take a few minutes)
  [ ] Databricks workspace state Succeeded with a workspaceUrl
  [ ] access connector identity holds Storage Blob Data Contributor and Storage Queue Data Contributor
EOF
