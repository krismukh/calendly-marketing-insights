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
| 4. Scheduling, CI/CD, observability | Databricks job, GitHub Actions deployment, alert | Scripts ready; setup pending |
| 5. Dashboard | Streamlit application | Not started |
| 6. Subscription and validation | Webhook subscription, live bookings, validation report | Not started |

SME approval of the architecture was received on 2026-10-27 (decision 20).

## Architecture

![Architecture](docs/Calendly_Pipeline_Architecture.png)

Lambda architecture on Azure (proposal Section 4):

- **Speed layer.** An HTTP-triggered Azure Function (`fn_calendly_receiver`) verifies each
  Calendly `invitee.created` webhook and lands the raw event in the Bronze container within
  seconds. An hourly Azure Databricks job merges new events into the Bronze and Silver Delta
  tables.
- **Batch layer.** A timer-triggered function (`fn_spend_fetcher`) lands the previous day's
  spend file from the public bucket after 06:00 AM Eastern. A daily Databricks job at
  06:30 AM Eastern rebuilds Silver and Gold over the full history.
- **Serving layer.** Gold Delta tables, read by the Streamlit dashboard.

| Component | Azure resource |
|---|---|
| Webhook receiver, spend fetcher | Function App `func-calendly-kcm` (Linux Consumption, Python 3.11) |
| Delta Lake | ADLS Gen2 `stcalendlykcm`, containers `bronze`, `silver`, `gold` |
| Processing and scheduling | Azure Databricks `dbw-calendly-kcm` (Workflows, single-node job clusters) |
| Secrets | Key Vault `kv-calendly-kcm`; Key Vault-backed secret scope `calendly` |
| Monitoring | Application Insights `appi-calendly-kcm`; Databricks job notifications; Azure Monitor alerts |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml`) |

## Repository layout

| Path | Content |
|---|---|
| `docs/` | Architecture proposal (Word), draw.io diagram, decision log, phase runbooks |
| `infra/` | `create_environment.sh`, `verify_environment.sh`, `configure_databricks.sh`, `deploy_function.sh`, `create_job.sh`, `create_monitoring.sh` |
| `src/` | Azure Functions project root: `function_app.py`, `host.json`, `requirements.txt` |
| `src/calendly_pipeline/` | Shared modules: `config.py`, `verify.py` (signature), `events.py` (parsing, landing paths), `landing.py` (ADLS writes), `spend_client.py` |
| `notebooks/` | Databricks notebooks in source form (Phase 3) |
| `jobs/` | `calendly_pipeline.json`, the Databricks job definition |
| `dashboards/` | Streamlit application (Phase 5) |
| `tests/` | pytest unit tests; `tests/fixtures/` holds the sample event and spend records from the brief |
| `scripts/` | `check_spend_source.py`, `send_test_event.py`; later `reload_range.py` |

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
first run; `docs/phase4_operations.md` for the job, CI/CD, monitoring, and reload.

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/calendly?code=<function key>` | function key (+ Calendly signature when enabled) | webhook receiver; this is the URL given to the program |
| `GET /api/health` | anonymous | liveness and configuration presence, no secrets |
| `GET /api/spend/fetch?code=<function key>` | function key | run the spend fetch on demand |

## Why this stack

To be completed with the final submission (brief, Step 6): the reason for each technology
chosen, with reference to the proposal.
