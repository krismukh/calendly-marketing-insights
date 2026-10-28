# Phase 3: Delta Lake layers

Three Databricks notebooks in `notebooks/`, run in order on a single-node cluster. Each
rebuilds its layer in full from the layer below (decision 25), so any run is idempotent and a
reload of any period is simply a rerun.

| Notebook | Reads | Writes |
|---|---|---|
| `01_bronze` | `bronze/calendly/landing/**.json`, `bronze/spend/landing/*.json` | `calendly.bronze.calendly_events`, `calendly.bronze.spend_files` |
| `02_silver` | Bronze tables | `calendly.silver.channel_map`, `silver.bookings`, `silver.meetings`, `silver.spend` |
| `03_gold` | Silver tables | six `calendly.gold.*` metric tables, `gold.pipeline_runs`, CSV export under `gold/export/` |

Rules applied in Silver: latest delivery per invitee and event wins; a canceled event sets
`status = canceled` and `is_canceled = true` on the booking; channel comes from the event type
URI (`other` for non-campaign types); dates and time slots are in Eastern time; for spend, the
most recent file wins per date and channel; no invitee name, email, or phone leaves Bronze.

Gold: `daily_bookings_by_channel`, `daily_spend_and_cpb` (CPB null when bookings = 0),
`channel_attribution` (ranked), `bookings_by_time_slot`, `employee_weekly_meetings`,
`employee_meeting_load`. `pipeline_runs` records counts and a reconciliation check
(distinct created invitees in Bronze = Silver bookings); the notebook fails if it does not hold.

## First run (Databricks workspace, in the browser)

1. Open https://adb-7405605822390071.11.azuredatabricks.net and sign in.
2. Left menu, **Compute**, **Create compute**. Name `single-node`, choose **Single node**,
   the latest **LTS** runtime, the smallest node type offered (Standard_DS3_v2 or similar),
   **Terminate after 20 minutes of inactivity**. Click **Create compute**. Takes 3 to 5 minutes.
3. Left menu, **Workspace**, open your user folder, click the kebab menu (three dots), **Import**,
   choose **File**, and select `notebooks\01_bronze.py` from the repository on your workstation.
   Repeat for `02_silver.py` and `03_gold.py`.
4. Open `01_bronze`, attach it to `single-node` (top right), click **Run all**. Expected: row
   counts printed for both Bronze tables and a five-row spend summary.
5. Open `02_silver`, **Run all**. Expected: four row counts and two summary tables.
6. Open `03_gold`, **Run all**. Expected: six row counts, the counts dictionary with
   `reconciled: True`, and "exported to abfss://gold@...".
7. Left menu, **Catalog**, expand `calendly`: `bronze` (2 tables), `silver` (4), `gold` (7).
8. Take screenshots of the three notebook outputs for the run record.

Phase 4 turns the three notebooks into two scheduled jobs; until then, rerun them by hand.

## Test data

The smoke-test events from Phase 2 land under `calendly/landing/2025/07/09/` and appear in
Silver with channel `other`. Delete them before the validation window starts:

```
az storage blob delete-batch --account-name stcalendlykcm --source bronze --pattern "calendly/landing/2025/07/09/*" --auth-mode login
```

## Run record

- 2026-10-28, serverless compute, notebooks imported to `/Users/krismukh@hotmail.com/`.
- Bronze: 2,790 spend rows (31 files, 90 each); test events present.
- Silver: 2 bookings (test, channel `other`, one canceled); spend 180 rows, 2026-08-29 to 2026-10-27, $97,268.32.
- Gold: six tables written; reconciliation passed; CSV export at `gold/export/`.
