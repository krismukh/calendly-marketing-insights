"""Post the sample Calendly event to the deployed receiver, with a signature.

Usage (virtual environment active, .env filled in with FUNCTION_URL and FUNCTION_KEY):

    python scripts/send_test_event.py                 # invitee.created from the fixture
    python scripts/send_test_event.py --canceled      # same invitee, as invitee.canceled
    python scripts/send_test_event.py --new-uuid      # fresh invitee uuid, so a new file lands
    python scripts/send_test_event.py --unsigned      # omit the signature header

FUNCTION_URL is the base URL, for example https://func-calendly-kcm.azurewebsites.net.
If CALENDLY_SIGNING_KEY is set in .env, the request is signed with it; otherwise a
throwaway key is used (accepted while VERIFY_SIGNATURE is false on the Function App).
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from calendly_pipeline.verify import HEADER_NAME, build_header  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_invitee_created.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--canceled", action="store_true", help="send as invitee.canceled")
    parser.add_argument("--new-uuid", action="store_true", help="replace the invitee uuid")
    parser.add_argument("--unsigned", action="store_true", help="omit the signature header")
    args = parser.parse_args()

    load_dotenv()
    base_url = os.getenv("FUNCTION_URL", "").rstrip("/")
    key = os.getenv("FUNCTION_KEY", "")
    signing_key = os.getenv("CALENDLY_SIGNING_KEY") or "local-test-key"
    if not base_url or not key:
        print("Set FUNCTION_URL and FUNCTION_KEY in .env first.")
        return 1

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if args.canceled:
        body["event"] = "invitee.canceled"
        body["payload"]["status"] = "canceled"
    if args.new_uuid:
        new = str(uuid.uuid4())
        body["payload"]["uri"] = body["payload"]["uri"].rsplit("/", 1)[0] + "/" + new
    raw = json.dumps(body).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if not args.unsigned:
        headers[HEADER_NAME] = build_header(signing_key, raw)

    url = f"{base_url}/api/calendly?code={key}"
    response = requests.post(url, data=raw, headers=headers, timeout=30)
    print(f"HTTP {response.status_code}")
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
