# Calendly Marketing Insights

Data Engineering Project 6. A pipeline that joins Calendly booking events, received through
webhooks, with daily marketing spend data, stores the data in Delta Lake on Azure Data Lake
Storage Gen2 in Bronze, Silver, and Gold layers, and presents six marketing and
calendar-optimization metrics in a Streamlit dashboard.

Implemented on Microsoft Azure following the Databricks reference design in the brief.
The architecture proposal and diagram are in `docs/`.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0. Preparation | Repository, fixtures, decision log, spend source check | Complete |
| 1. Environment | `infra/create_environment.sh`, `infra/configure_databricks.sh` | Complete |
| 2. Capture | `fn_calendly_receiver`, `fn_spend_fetcher`, unit tests | Complete; endpoint shared with the program |
| 3. Delta Lake layers | `01_bronze`, `02_silver`, `03_gold` notebooks | Complete; first run 2026-10-28 |
| 4. Scheduling, CI/CD, observability | Databricks job, GitHub Actions deployment, alert | Complete; job and deployment live 2026-10-28 |
| 5. Dashboard | Streamlit application | Complete; run locally against synced Gold exports |
| 6. Subscription and validation | Webhook subscription, live bookings, validation report | Waiting on the program: subscription and signing key requested 2026-10-27, followed up 2026-10-29 |

SME approval of the architecture was received on 2026-10-27 (decision 20).

## Architecture

![Architecture](docs/Calendly_Pipeline_Architecture.png)

Lambda architecture on Azure (proposal Section 4):

- **Speed layer.** An HTTP-triggered Azure Function (`fn_calendly_receiver`) verifies each
  Calendly `invitee.created` and `invitee.canceled` webhook and lands the raw event in the
  Bronze container within seconds. The hourly Azure Databricks job `calendly_pipeline`
  rebuilds the Bronze and Silver Delta tables from the landing files (decisions 25 and 28).
- **Batch layer.** A timer-triggered function (`fn_spend_fetcher`) lands the previous day's
  spend file from the public bucket after 06:00 AM Eastern. The same hourly job rebuilds
  Silver and Gold over the full history, so a day's spend and CPB appear within the hour of
  the file landing.
- **Serving layer.** Gold Delta tables, exported to CSV for the Streamlit dashboard.

| Component | Azure resource |
|---|---|
| Webhook receiver, spend fetcher | Function App `func-calendly-kcm` (Linux Consumption, Python 3.11) |
| Delta Lake | ADLS Gen2 `stcalendlykcm`, containers `bronze`, `silver`, `gold` |
| Processing and scheduling | Azure Databricks `dbw-calendly-kcm` (Workflows, serverless compute) |
| Secrets | Key Vault `kv-calendly-kcm`; Key Vault-backed secret scope `calendly` |
| Monitoring | Application Insights `appi-calendly-kcm`; Databricks job notifications; Azure Monitor alerts |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml`) |

## Repository layout

| Path | Content |
|---|---|
| `docs/` | Architecture proposal (Word), draw.io diagram, decision log, phase runbooks, final report, presentation |
| `infra/` | `create_environment.sh`, `verify_environment.sh`, `configure_databricks.sh`, `deploy_function.sh`, `create_job.sh`, `create_monitoring.sh` |
| `src/` | Azure Functions project root: `function_app.py`, `host.json`, `requirements.txt` |
| `src/calendly_pipeline/` | Shared modules: `config.py`, `verify.py` (signature), `events.py` (parsing, landing paths), `landing.py` (ADLS writes), `spend_client.py` |
| `notebooks/` | Databricks notebooks in source form (Phase 3) |
| `jobs/` | `calendly_pipeline.json`, the Databricks job definition |
| `dashboards/` | `app.py` (Streamlit, seven pages), `sync_gold.cmd`, `requirements.txt` |
| `tests/` | pytest unit tests; `tests/fixtures/` holds the sample event and spend records from the brief |
| `scripts/` | `check_spend_source.py`, `send_test_event.py` |

## Local setup (workstation)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
ruff check . && ruff format --check . && pytest -q
python scripts\check_spend_source.py
```

`.env` is ignored by git. The spend bucket is public, so the check needs no credentials.

## Azure environment

See `docs/phase1_environment.md` for the resources, settings, run instructions, and
verification checklist, and `docs/phase2_capture.md` for the functions, their behavior,
deployment, and the smoke test; `docs/phase3_delta_layers.md` for the notebooks and their
first run; `docs/phase4_operations.md` for the job, CI/CD, monitoring, and reload; `docs/phase5_dashboard.md`
for the dashboard.

## Dashboard

```
pip install -r dashboards\requirements.txt
az login
dashboards\sync_gold.cmd
streamlit run dashboards\app.py
```

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/calendly?code=<function key>` | function key (+ Calendly signature when enabled) | webhook receiver; this is the URL given to the program |
| `GET /api/health` | anonymous | liveness and configuration presence, no secrets |
| `GET /api/spend/fetch?code=<function key>` | function key | run the spend fetch on demand |

## Why this stack

Each choice, with the proposal section or decision that records it.

| Technology | Why it was chosen |
|---|---|
| Microsoft Azure | The same platform as Projects 2 through 5, so the environment scripts, Functions pattern, and operating practice carry over; every AWS service in the brief has a direct Azure equivalent (proposal Section 4.2; decision 1). |
| Azure Functions (Python, Linux Consumption) | A public HTTPS endpoint with no servers to run and a timer trigger for the daily spend fetch in the same project; scales to zero between deliveries, which suits tens of events per day. Managed identity and Key Vault references keep secrets out of code (decisions 12, 13). |
| Azure Data Lake Storage Gen2 | Hierarchical namespace storage that Delta Lake writes to natively; raw landing files are retained because spend files older than 30 days leave the public index and cannot be re-fetched (decisions 4, 18). |
| Delta Lake, Bronze / Silver / Gold | Required by the brief. ACID writes mean readers never see a partial Gold table; the three layers separate raw retention, cleaned facts without personal data, and the metric tables (decisions 10, 25). |
| Azure Databricks (serverless, Workflows) | The direct equivalent of the Databricks reference design in the brief; Delta is its native format and Workflows gives scheduling, retries, and failure e-mail without a separate orchestrator; chosen over Synapse Spark to add a new tool on the final project (decisions 2, 3, 28). Unity Catalog with a managed-identity storage credential removes storage keys from notebooks (decision 14). |
| Full rebuild each run | At this volume the three notebooks run in about two minutes, so rebuilding every table from the retained landing files is simpler and safer than Auto Loader checkpoints and MERGE: every run is idempotent and a reload is a rerun (decision 25). |
| Azure Key Vault | Holds the Calendly signing key; read by the Function App through a Key Vault reference and by Databricks through a Key Vault-backed secret scope (decisions 14, 17). |
| Application Insights, Azure Monitor, Databricks notifications | Per-request traces for the webhook, an alert on HTTP 5xx responses, and an e-mail on any failed job run (proposal Section 7.2). |
| GitHub Actions | Required by the brief. Lint and tests on every push; a green build deploys the Function App and imports the notebooks and job definition, so the repository is the single source of truth (decision 30). |
| Streamlit | Required by the brief. Reads CSV exports of the Gold tables, which avoids a SQL warehouse or storage credentials in the dashboard (decision 26). |
