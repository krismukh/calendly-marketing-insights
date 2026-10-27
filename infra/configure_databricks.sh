#!/usr/bin/env bash
# =============================================================================
# Calendly Marketing Insights (Project 6): Databricks workspace configuration
#
# Run AFTER create_environment.sh, from Azure Cloud Shell (bash), signed in to
# the same subscription. Uses the Databricks CLI with Azure CLI authentication
# (no tokens to create or store). Creates, idempotently:
#
#   1. Key Vault-backed secret scope  "calendly"  -> kv-calendly-kcm
#   2. Unity Catalog storage credential  "cred-calendly-adls"  (access connector identity)
#   3. External locations for the bronze, silver, gold, and metastore containers
#   4. Catalog "calendly" with schemas bronze, silver, gold (one per container)
#
# Prerequisite: the workspace must be attached to a Unity Catalog metastore. New
# workspaces in most regions receive one automatically; if "metastores current"
# fails, create or assign a metastore in the account console
# (https://accounts.azuredatabricks.net, Catalog) and rerun this script.
# =============================================================================
set -euo pipefail

RG="rg-calendly"
STORAGE="stcalendlykcm"
KEYVAULT="kv-calendly-kcm"
DBW_WORKSPACE="dbw-calendly-kcm"
ACCESS_CONNECTOR="dbac-calendly-kcm"
SCOPE="calendly"
CREDENTIAL="cred-calendly-adls"
CATALOG="calendly"
DFS="${STORAGE}.dfs.core.windows.net"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '    exists: %s\n' "$*"; }

# ----------------------------------------------------------------------------
# Databricks CLI (installed per Cloud Shell session into ~/.local/bin)
# ----------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"
if ! command -v databricks >/dev/null 2>&1; then
  log "Installing the Databricks CLI"
  mkdir -p "$HOME/.local/bin"
  VERSION=$(curl -fsSL https://api.github.com/repos/databricks/cli/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p')
  curl -fsSL "https://github.com/databricks/cli/releases/download/v${VERSION}/databricks_cli_${VERSION}_linux_amd64.zip" -o /tmp/databricks_cli.zip
  unzip -o -q /tmp/databricks_cli.zip -d "$HOME/.local/bin"
  chmod +x "$HOME/.local/bin/databricks"
fi
databricks --version

# ----------------------------------------------------------------------------
# Workspace connection (Azure CLI credentials)
# ----------------------------------------------------------------------------
DBW_URL=$(az databricks workspace show -n "$DBW_WORKSPACE" -g "$RG" --query workspaceUrl -o tsv)
export DATABRICKS_HOST="https://${DBW_URL}"
export DATABRICKS_AUTH_TYPE="azure-cli"
log "Workspace $DATABRICKS_HOST"
databricks current-user me --output json | sed -n 's/.*"userName": *"\([^"]*\)".*/    signed in as \1/p'

KV_ID=$(az keyvault show -n "$KEYVAULT" -g "$RG" --query id -o tsv)
KV_URI=$(az keyvault show -n "$KEYVAULT" -g "$RG" --query properties.vaultUri -o tsv)
DBAC_ID=$(az databricks access-connector show -n "$ACCESS_CONNECTOR" -g "$RG" --query id -o tsv)

# ----------------------------------------------------------------------------
# 1. Secret scope backed by Key Vault
# ----------------------------------------------------------------------------
log "1. Secret scope $SCOPE -> $KEYVAULT"
if databricks secrets list-scopes --output json | grep -q "\"name\": *\"$SCOPE\""; then skip "$SCOPE"; else
  databricks secrets create-scope --json "{
    \"scope\": \"$SCOPE\",
    \"scope_backend_type\": \"AZURE_KEYVAULT\",
    \"backend_azure_keyvault\": {\"resource_id\": \"$KV_ID\", \"dns_name\": \"$KV_URI\"}
  }"
fi
printf '    secrets visible through the scope:\n'
databricks secrets list-secrets "$SCOPE" --output json | sed -n 's/.*"key": *"\([^"]*\)".*/      \1/p'

# ----------------------------------------------------------------------------
# 2. Unity Catalog: metastore check and storage credential
# ----------------------------------------------------------------------------
log "2. Unity Catalog metastore"
if ! databricks metastores current >/dev/null 2>&1; then
  echo "No metastore is assigned to this workspace. Assign one in the account console, then rerun." >&2
  exit 1
fi
databricks metastores current --output json | sed -n 's/.*"metastore_id": *"\([^"]*\)".*/    metastore \1/p'

log "2b. Storage credential $CREDENTIAL (access connector identity)"
if databricks storage-credentials get "$CREDENTIAL" >/dev/null 2>&1; then skip "$CREDENTIAL"; else
  databricks storage-credentials create --json "{
    \"name\": \"$CREDENTIAL\",
    \"azure_managed_identity\": {\"access_connector_id\": \"$DBAC_ID\"},
    \"comment\": \"Managed identity of $ACCESS_CONNECTOR; Storage Blob Data Contributor on $STORAGE\"
  }" >/dev/null
fi

# ----------------------------------------------------------------------------
# 3. External locations, one per container
# ----------------------------------------------------------------------------
log "3. External locations"
for c in bronze silver gold metastore; do
  name="loc-calendly-$c"
  if databricks external-locations get "$name" >/dev/null 2>&1; then skip "$name"; else
    databricks external-locations create --json "{
      \"name\": \"$name\",
      \"url\": \"abfss://${c}@${DFS}/\",
      \"credential_name\": \"$CREDENTIAL\",
      \"comment\": \"Container $c of $STORAGE\"
    }" >/dev/null
    printf '    created %s -> abfss://%s@%s/\n' "$name" "$c" "$DFS"
  fi
done

# ----------------------------------------------------------------------------
# 4. Catalog and schemas
# ----------------------------------------------------------------------------
log "4. Catalog $CATALOG and schemas bronze, silver, gold"
if databricks catalogs get "$CATALOG" >/dev/null 2>&1; then skip "catalog $CATALOG"; else
  databricks catalogs create --json "{
    \"name\": \"$CATALOG\",
    \"storage_root\": \"abfss://metastore@${DFS}/catalog\",
    \"comment\": \"Calendly Marketing Insights (Project 6)\"
  }" >/dev/null
fi
for s in bronze silver gold; do
  if databricks schemas get "${CATALOG}.${s}" >/dev/null 2>&1; then skip "schema ${CATALOG}.${s}"; else
    databricks schemas create --json "{
      \"name\": \"$s\",
      \"catalog_name\": \"$CATALOG\",
      \"storage_root\": \"abfss://${s}@${DFS}/tables\",
      \"comment\": \"$s layer; managed tables stored in the $s container\"
    }" >/dev/null
    printf '    created %s.%s -> abfss://%s@%s/tables\n' "$CATALOG" "$s" "$s" "$DFS"
  fi
done

log "Done."
cat <<EOF
  Catalog    : $CATALOG (schemas bronze, silver, gold)
  Credential : $CREDENTIAL
  Scope      : $SCOPE (secrets read in notebooks with dbutils.secrets.get("$SCOPE", "calendly-signing-key"))
  Workspace  : $DATABRICKS_HOST
EOF
