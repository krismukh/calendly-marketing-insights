# Phase 5: Dashboard

A single-file Streamlit application, `dashboards/app.py`, with the six metric pages from the
brief and an operations page. It reads the CSV exports that notebook `03_gold` writes to
`gold/export/`, synced to `dashboards/data/export/` (ignored by git) with
`dashboards/sync_gold.cmd` (decision 26).

| Page | Visualizations | Gold source |
|---|---|---|
| 1.1 Daily calls booked | line chart by source; daily comparison table | `daily_bookings_by_channel` |
| 1.2 Cost per booking | KPI tiles (bookings, spend, average CPB); bar chart CPB by channel; sortable table | `daily_spend_and_cpb` |
| 1.3 Bookings trend | daily or weekly line; cumulative area | `daily_bookings_by_channel` |
| 1.4 Channel attribution | leaderboard; CPB heatmap by channel and month; top sources bar | `channel_attribution`, `daily_spend_and_cpb` |
| 1.5 Time slots | heatmap hour by day of week; histogram by hour; pie by day of week | `bookings_by_time_slot` |
| 1.6 Meeting load | KPIs; bar of average meetings per week; weekly line; table | `employee_meeting_load`, `employee_weekly_meetings` |
| Operations | spend-through date, latest booking, spend days loaded; daily spend chart | `daily_spend_and_cpb` |

Pages show an informational notice instead of failing when a table is empty (no campaign
bookings until the subscription is active). All seven pages were exercised with Streamlit's
test harness against sample data before delivery.

## Run (workstation)

```
pip install -r dashboards\requirements.txt
az login
dashboards\sync_gold.cmd
streamlit run dashboards\app.py
```

Rerun `sync_gold.cmd` whenever fresh Gold data is wanted; the hourly job refreshes the exports.
Screenshots for the submission go in `docs/screenshots/`.
