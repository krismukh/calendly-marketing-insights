# Phase 2: Capture

Two Azure Functions in one Function App (`func-calendly-kcm`), Python v2 programming model,
project root `src/`.

## Functions

| Function | Trigger | Route and auth | Purpose |
|---|---|---|---|
| `fn_calendly_receiver` | HTTP POST | `/api/calendly?code=<function key>` | Verify the Calendly signature (when enabled), parse the event, write it to the Bronze landing zone, return 200 |
| `health` | HTTP GET | `/api/health` (anonymous) | Liveness and configuration presence; no secrets |
| `fn_spend_fetcher` | Timer | `SPEND_FETCH_SCHEDULE` (`0 15,45 10-16 * * *` UTC) | Read `file_index.json`, land every listed file within the look-back window that is not yet landed |
| `spend_fetch_now` | HTTP GET or POST | `/api/spend/fetch?code=<function key>` | Run the spend fetch on demand (testing and reloads) |

## Receiver behavior

| Case | Response | Landed |
|---|---|---|
| Valid `invitee.created` or `invitee.canceled` | 200 `{"status": "landed", "path": ...}` | Yes, `bronze/calendly/landing/{yyyy}/{MM}/{dd}/{event}_{invitee_uuid}.json` |
| Same event delivered again | 200 | Overwritten at the same path (idempotent) |
| Other event types, malformed JSON, missing payload | 200 `{"status": "skipped"}` | No; acknowledged so Calendly does not retry |
| Missing or invalid signature (`VERIFY_SIGNATURE=true`) | 401 | No |
| Storage write failure | 500 | No; Calendly retries the delivery |

The landing document wraps the raw event: `received_at_utc`, `signature_verified`,
`event_name`, `invitee_uuid`, `event_type_uri`, and `body` (the webhook body unchanged).
The date in the path is the event's `created_at` in UTC.

Signature verification follows Calendly's scheme: header `Calendly-Webhook-Signature`
with `t=<unix seconds>,v1=<hex HMAC-SHA256>` computed over `<t>.<raw body>` with the
subscription signing key; signatures older than `SIGNATURE_TOLERANCE_SECONDS` (300) are
rejected. Verification stays off (`VERIFY_SIGNATURE=false`) until the program shares the
key; the function key in the URL protects the endpoint in the meantime.

## Spend fetcher behavior

- Reads `file_index.json` (format `{"files": [...]}`, decision 18).
- Considers files whose date is within `SPEND_LOOKBACK_DAYS` (35) of today in Eastern time.
- Downloads each file not already present under `bronze/spend/landing/`, validates it (JSON
  array; every record has exactly `date`, `channel`, `spend`; known channel; non-negative
  spend; no duplicate date and channel), and writes it with `file_date` and `source_url`
  metadata. Invalid files go to `bronze/spend/quarantine/` with the reason.
- Logs one JSON summary per run with `outcome` `ok`, `partial`, or `latest_missing`
  (the Day-1 file is not yet in the index). The schedule runs every 30 minutes from
  10:15 to 16:45 UTC, so a late file is picked up by a later run; Phase 4 adds the alert
  for `latest_missing` after the last run of the day.

## Local checks (workstation)

```
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest -q
```

46 tests: signature verification, event parsing and landing paths, spend index parsing and
validation, fetcher behavior with a fake session, and the receiver with an in-memory
landing zone.

## Deployment (Cloud Shell)

```
git clone https://github.com/krismukh/calendly-marketing-insights.git
cd calendly-marketing-insights
bash infra/deploy_function.sh
```

The script prints the health URL, the webhook URL with its key, and the two lines to put in
`.env` on the workstation (`FUNCTION_URL`, `FUNCTION_KEY`).

## Smoke test (workstation)

```
python scripts\send_test_event.py
python scripts\send_test_event.py --canceled
python scripts\send_test_event.py --new-uuid
```

Expected: `HTTP 200` and `{"status": "landed", "path": "calendly/landing/2025/07/09/..."}`.
Then confirm in the portal (storage account `stcalendlykcm`, container `bronze`, folder
`calendly/landing/2025/07/09/`) that the files exist, and run the spend fetch once:

```
curl "https://func-calendly-kcm.azurewebsites.net/api/spend/fetch?code=<FUNCTION_KEY>"
```

Expected: a JSON summary with `landed` listing the 30 files from the index on the first run
and `latest_available: true`; `bronze/spend/landing/` then holds 30 files.

## Hand-off to the program

After the smoke test, share the webhook URL (with the key) and ask for the subscription to
be created at organization scope for `invitee.created` and `invitee.canceled`, and for the
signing key to be shared through a private channel. When the key arrives:

```
az keyvault secret set --vault-name kv-calendly-kcm -n calendly-signing-key --value '<key>'
az functionapp config appsettings set -n func-calendly-kcm -g rg-calendly --settings VERIFY_SIGNATURE=true
```

## Run record

_(to be filled in after deployment: date, health output, smoke test results, spend fetch summary)_
