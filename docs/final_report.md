# Final Report: Calendly Marketing Insights

Data Engineering Project 6, DE Academy. Krishna C. Mukherjee. Draft of 2026-10-29; Section 6
is completed when the validation window closes.

## 1. Objective

Join Calendly booking events for three paid-advertising campaigns (Facebook, YouTube, TikTok)
with the daily marketing spend published for those channels, and present six metrics on a
Streamlit dashboard: daily calls booked by source, cost per booking by channel, bookings
trend, channel attribution, booking volume by time slot and day of week, and meeting load per
employee. The brief prescribes a Lambda architecture, Delta Lake with Bronze, Silver, and Gold
layers, GitHub CI/CD, and written SME approval before implementation.

## 2. What was delivered

| Deliverable | Location |
|---|---|
| Architecture proposal (SME approved 2026-10-27) and diagram | `docs/Calendly_Marketing_Insights_Architecture_Proposal.docx`, `docs/Calendly_Pipeline_Architecture.drawio` and `.png` |
| Decision log (30 decisions) | `docs/decision_log.md` |
| Environment, Databricks configuration, deployment, job, and monitoring scripts | `infra/` |
| Webhook receiver, spend fetcher, health endpoint, shared package, 46 unit tests | `src/`, `tests/` |
| Bronze, Silver, and Gold notebooks and the hourly job definition | `notebooks/`, `jobs/calendly_pipeline.json` |
| GitHub Actions workflow (lint, tests, Function App deployment, notebook and job deployment) | `.github/workflows/ci.yml` |
| Streamlit dashboard (seven pages) and Gold sync script | `dashboards/` |
| Phase runbooks with run records | `docs/phase1_environment.md` to `docs/phase5_dashboard.md` |
| Presentation | `docs/Calendly_Marketing_Insights_Presentation.pptx` |
| Technology rationale | `README.md`, section "Why this stack" |

## 3. Architecture

Lambda architecture on Azure (proposal Section 4).

- **Speed layer.** `fn_calendly_receiver` (Azure Functions, HTTP trigger) verifies the
  Calendly signature when enabled, accepts `invitee.created` and `invitee.canceled`, and
  lands the raw event in `bronze/calendly/landing/{yyyy}/{MM}/{dd}/{event}_{invitee_uuid}.json`
  within seconds. The hourly Databricks job `calendly_pipeline` rebuilds Bronze and Silver from
  the landing files.
- **Batch layer.** `fn_spend_fetcher` (timer trigger, every 30 minutes from 06:15 to 12:45
  Eastern in summer) reads `file_index.json` and lands any spend file not yet present. The
  hourly job rebuilds Silver and Gold over the full history.
- **Serving layer.** Six Gold Delta tables in Unity Catalog (`calendly.gold`), exported to CSV
  for the dashboard.

| Component | Resource |
|---|---|
| Functions | `func-calendly-kcm` (Linux Consumption, Python 3.11, managed identity) |
| Data lake | `stcalendlykcm`, containers `bronze`, `silver`, `gold` |
| Processing | `dbw-calendly-kcm` (Premium, serverless compute, Unity Catalog, job `calendly_pipeline`) |
| Secrets | `kv-calendly-kcm`; secret scope `calendly` |
| Monitoring | `appi-calendly-kcm`; alert `alr-calendly-failures`; action group `ag-calendly`; job failure e-mail |

## 4. Data model and rules

| Layer | Tables | Rules |
|---|---|---|
| Bronze | `calendly_events`, `spend_files` | Raw JSON as landed, with file name and load time; retained permanently because spend files leave the public index after 30 days. |
| Silver | `channel_map`, `bookings`, `meetings`, `spend` | Latest delivery per invitee and event wins; a canceled event marks the booking canceled; channel derived from the event type URI (`other` for non-campaign types); dates and time slots in Eastern time; for spend, the most recent file wins per date and channel; no invitee name, e-mail, or phone leaves Bronze. |
| Gold | `daily_bookings_by_channel`, `daily_spend_and_cpb`, `channel_attribution`, `bookings_by_time_slot`, `employee_weekly_meetings`, `employee_meeting_load`, `pipeline_runs` | Marketing metrics use the three campaign event types only; meeting load uses all event types (SME decision); CPB is null on days with spend and no bookings; `pipeline_runs` records counts and a reconciliation check that fails the run if Bronze and Silver disagree. |

## 5. Operations

- Hourly job: three tasks, about two minutes on serverless compute; two retries; e-mail on
  failure. First run 2026-10-28 (decision 29).
- Deployment: every push to `main` runs lint and tests, deploys the Function App from the
  publish profile, and imports the notebooks and job definition with the Databricks CLI. Seven
  runs green as of 2026-10-28.
- Spend ingestion: 31 files landed by 2026-10-28; Silver spend 2026-08-29 to 2026-10-27,
  $97,268.32 in total; channel totals YouTube $37,967.04, Facebook $35,636.89, TikTok $23,664.39.
- Reload: rerun the job; every layer is rebuilt from the retained landing files.
- Security: function-key authentication on the webhook route, Calendly signature verification
  once the signing key is received, managed identity for storage, Key Vault for the signing key,
  no personal data beyond Bronze.

## 6. Validation (to be completed)

The webhook endpoint URL was shared with the program on 2026-10-27 and the subscription and
signing key requested; the request was followed up on 2026-10-29.

| Check | Result |
|---|---|
| Subscription created by the program | pending |
| Signature verification enabled (`VERIFY_SIGNATURE=true`) | pending |
| Test events from Phase 2 deleted from Bronze | pending |
| First live `invitee.created` landed and visible in Silver within the hour | pending |
| First `invitee.canceled` reflected as a canceled booking | pending |
| Spend for the previous day present by 07:00 Eastern on each day of the window | pending |
| CPB computed for each channel with bookings | pending |
| Dashboard pages 1.1 to 1.6 populated | pending |
| Reconciliation check passed on every hourly run | pending |

Evidence already in hand: Phase 2 smoke test (created, canceled, and new-uuid test events
landed and processed through Silver and Gold, `docs/phase2_capture.md`); 31 daily spend files
ingested without manual intervention; seven consecutive green deployments.

## 7. Known limitations

- The dashboard runs on the workstation against synced CSV exports; deployment to Azure App
  Service is documented as an option in the proposal (Section 12, item 9).
- UTM parameters are null in the sample event, so attribution is by event type; UTM fields are
  kept in Silver for use if they appear.
- No historical backfill: metrics begin with the first live booking after the subscription is
  created (SME decision).
