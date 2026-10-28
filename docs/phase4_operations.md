# Phase 4: Scheduling, CI/CD, and monitoring

## Scheduling

One Databricks job, `calendly_pipeline` (`jobs/calendly_pipeline.json`), runs the three
notebooks in order on serverless compute every hour at :05 UTC, with two retries five minutes
apart and an e-mail on failure. One hourly job replaces the proposal's separate hourly and
daily jobs (decision 28): at this volume a full rebuild costs about the same as an
incremental one, and the Gold tables, which carry Day-1 spend, are refreshed hourly as the
SME asked. The spend fetcher's own schedule (every 30 minutes, 10:15 to 16:45 UTC) is
unchanged.

`infra/create_job.sh` creates or resets the job from the JSON and starts one run.

## CI/CD (`.github/workflows/ci.yml`)

| Job | Trigger | Steps |
|---|---|---|
| `test` | every push and pull request | ruff, pytest, shell syntax |
| `deploy-function` | push to `main`, after `test` | zip deploy of `src/` to `func-calendly-kcm` with remote build; health check |
| `deploy-notebooks` | push to `main`, after `test` | import `notebooks/` into the workspace; create or reset the job from `jobs/calendly_pipeline.json` |

Repository secrets required: `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` (XML from the Function
App), `DATABRICKS_HOST` (`https://adb-7405605822390071.11.azuredatabricks.net`), and
`DATABRICKS_TOKEN` (a personal access token from the workspace).

## Monitoring

| Signal | Mechanism |
|---|---|
| Databricks job failure (any of the three notebooks, including the reconciliation check) | Job e-mail notification on failure (in the job definition) |
| Function App server errors (receiver landing failure, fetcher crash) | `alr-calendly-failures`: Azure Monitor metric alert, HTTP 5xx > 0 in 5 minutes, action group `ag-calendly` e-mail (`infra/create_monitoring.sh`) |
| Spend file late or missing | Fetcher logs `outcome: latest_missing`; the dashboard shows the last spend date, so a stale date is visible at a glance |
| Row counts and reconciliation per run | `calendly.gold.pipeline_runs` |

## Reload

Every notebook rebuilds its layer in full, so a reload of any period is a rerun of the job
(**Run now** in the Databricks job page, or `databricks jobs run-now <job id>`). If a spend
file must be re-fetched, call `/api/spend/fetch` (it lands anything in the index that is
missing from `spend/landing/`); files older than the 30-day index window cannot be
re-fetched, which is why landed files are kept permanently (decision 18).

## Run record

_(job id, first scheduled run, CI run links, alert confirmation)_
