# Phase 1: Environment

`infra/create_environment.sh` creates every resource in Section 10 of the proposal.
It is idempotent: rerunning it after a partial failure skips what already exists.
`infra/configure_databricks.sh` then configures the inside of the Databricks workspace.

## Resources created by `create_environment.sh`

| Resource | Name | Notes |
|---|---|---|
| Resource group | `rg-calendly` | West US 3 |
| Data lake storage | `stcalendlykcm` | ADLS Gen2 (hierarchical namespace); containers `bronze`, `silver`, `gold`, `metastore`; HTTPS only; TLS 1.2; public blob access off |
| Function host storage | `stcalendlyfnkcm` | Required by the Functions runtime, which does not support hierarchical-namespace accounts for its own state (decision 12) |
| Key Vault | `kv-calendly-kcm` | RBAC mode; secret `calendly-signing-key` (placeholder until the program shares the key) |
| Log Analytics | `log-calendly-kcm` | Backing workspace for Application Insights; 30-day retention |
| Application Insights | `appi-calendly-kcm` | Workspace-based |
| Function App | `func-calendly-kcm` | Linux Consumption, Python 3.11, Functions v4, system-assigned identity, HTTPS only |
| Databricks workspace | `dbw-calendly-kcm` | Premium; managed resource group `rg-calendly-dbw-managed` |
| Access connector | `dbac-calendly-kcm` | System-assigned identity used by Unity Catalog to reach the data lake |

Role assignments:

| Identity | Role | Scope |
|---|---|---|
| Function App | Storage Blob Data Contributor | `stcalendlykcm` |
| Function App | Key Vault Secrets User | `kv-calendly-kcm` |
| Access connector | Storage Blob Data Contributor, Storage Queue Data Contributor | `stcalendlykcm` |
| Signed-in user | Storage Blob Data Contributor, Key Vault Secrets Officer | so that the script can create containers and secrets |

Application settings written to the Function App (consumed by the code in Phase 2):

| Setting | Value |
|---|---|
| `STORAGE_ACCOUNT_URL` | `https://stcalendlykcm.blob.core.windows.net` |
| `BRONZE_CONTAINER` | `bronze` |
| `CALENDLY_LANDING_PREFIX`, `SPEND_LANDING_PREFIX`, `SPEND_QUARANTINE_PREFIX` | `calendly/landing`, `spend/landing`, `spend/quarantine` |
| `SPEND_BASE_URL` | `https://dea-data-bucket.s3.us-east-1.amazonaws.com/calendly_spend_data` |
| `SPEND_FETCH_SCHEDULE` | `0 15,45 10-16 * * *` (UTC; every 30 minutes from 10:15 to 16:45, decision 13) |
| `SPEND_LOOKBACK_DAYS` | `35` (how far back the fetcher looks for files not yet landed) |
| `VERIFY_SIGNATURE`, `SIGNATURE_TOLERANCE_SECONDS` | `false` until the signing key is available; `300` |
| `CALENDLY_SIGNING_KEY` | Key Vault reference to `calendly-signing-key` |

No connection strings or keys for the data lake are stored in application settings; access
is through the managed identity. The only key present is the runtime's own
`AzureWebJobsStorage` for `stcalendlyfnkcm`, which the platform writes.

## Objects created by `configure_databricks.sh`

| Object | Name | Purpose |
|---|---|---|
| Secret scope | `calendly` | Key Vault-backed; exposes `calendly-signing-key` and any later secrets to notebooks |
| Storage credential | `cred-calendly-adls` | Unity Catalog credential using the access connector identity |
| External locations | `loc-calendly-bronze`, `-silver`, `-gold`, `-metastore` | One per container, so Unity Catalog may read and write each |
| Catalog | `calendly` | Storage root `abfss://metastore@stcalendlykcm.dfs.core.windows.net/catalog` |
| Schemas | `calendly.bronze`, `calendly.silver`, `calendly.gold` | Each with its storage root in the matching container, so managed Delta tables land in the right layer |

Tables are referenced in notebooks as `calendly.bronze.calendly_events`, `calendly.silver.bookings`,
`calendly.gold.daily_bookings_by_channel`, and so on.

## Running the scripts

1. Open Azure Cloud Shell (bash) at https://shell.azure.com in the Pay-As-You-Go
   subscription. Confirm with `az account show --query name`.
2. Clone the repository (the Cloud Shell home folder may reset between sessions, so
   clone each time):
   ```
   git clone https://github.com/krismukh/calendly-marketing-insights.git
   cd calendly-marketing-insights
   ```
3. Run the environment script:
   ```
   bash infra/create_environment.sh
   ```
   Expected runtime: 10 to 15 minutes, most of it the Databricks workspace (5 to 8
   minutes) and the Function App. Role propagation pauses of up to two minutes are
   built in.
4. Run `bash infra/verify_environment.sh` and keep the output for this document.
5. Run `bash infra/configure_databricks.sh`. The first run installs the Databricks CLI
   into `~/.local/bin`.
6. Open the workspace URL printed at the end, sign in with the same account, and confirm
   in Catalog Explorer that catalog `calendly` shows the three schemas.
7. Paste the verification output below and commit.

## Verification checklist

- [ ] `az resource list -g rg-calendly` shows 9 resources
- [ ] Containers `bronze`, `silver`, `gold`, `metastore` exist in `stcalendlykcm`
- [ ] Key Vault lists `calendly-signing-key`
- [ ] Function App state is Running and the identity holds the two roles
- [ ] Key Vault reference `CALENDLY_SIGNING_KEY` shows Resolved (may take a few minutes;
      rerun `verify_environment.sh` if it shows an error at first)
- [ ] Databricks workspace state Succeeded; the access connector identity holds its two roles
- [ ] Catalog `calendly` with schemas `bronze`, `silver`, `gold` visible in Catalog Explorer
- [ ] Secret scope `calendly` lists `calendly-signing-key`

## Run record

- Environment created 2026-10-27 from Cloud Shell; `verify_environment.sh` checklist satisfied.
- Databricks workspace URL: `https://adb-7405605822390071.11.azuredatabricks.net`
- Unity Catalog metastore assigned automatically; `configure_databricks.sh` completed after the
  role assignment described under Known issues.

## Known issues

- **403 when creating or listing the Key Vault-backed secret scope.** The scope is read by the
  AzureDatabricks service principal, which needs Key Vault Secrets User on the vault. The
  environment script now assigns it (decision 17); on a vault created before that change, run
  `az role assignment create --assignee-object-id $(az ad sp show --id 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d --query id -o tsv) --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $(az keyvault show -n kv-calendly-kcm -g rg-calendly --query id -o tsv)`
  and rerun `configure_databricks.sh`.

- **Key Vault name conflict.** Vault names are global and soft-deleted vaults keep their
  name for 90 days. The script recovers a soft-deleted `kv-calendly-kcm` automatically.
  If the name is held by someone else, change `KEYVAULT` in both scripts.
- **Consumption plan availability.** If `az functionapp create` reports that the
  Consumption plan is not available in West US 3, replace `--consumption-plan-location`
  with `--flexconsumption-location` to use the Flex Consumption plan; nothing else in the
  design changes.
- **Databricks quota.** A Premium workspace has no cost of its own; compute is billed only
  while a cluster runs. If workspace creation fails with a quota message, the subscription
  has no Databricks quota in West US 3; request it in the portal (Quotas) or change
  `LOCATION` in both scripts to a nearby region.
- **No Unity Catalog metastore.** If `configure_databricks.sh` stops at step 2, the
  workspace was not attached to a metastore automatically. In the account console
  (https://accounts.azuredatabricks.net), open Catalog, create a metastore in West US 3
  (no storage root needed) or assign the existing one to `dbw-calendly-kcm`, then rerun.
- **Databricks CLI flags.** The CLI changes between releases. Every create call passes a
  `--json` body, which matches the REST API and is stable; if a command still fails, run
  `databricks <group> <command> --help` and adjust.
- **Role propagation.** Azure RBAC assignments can take one to two minutes to take effect.
  The scripts retry container creation and secret creation; if a later step fails with an
  authorization error, rerun the script.

## Verification output

_(paste the output of `verify_environment.sh` here after the run)_
