"""Phase 0 check: confirm that the public spend index and the most recent spend file are
reachable, and report what they contain.

Usage (from the repository root, with the virtual environment active):

    python scripts/check_spend_source.py

Reads SPEND_BASE_URL from .env if present; otherwise uses the URL from the brief.
Writes nothing to disk unless --save is given, in which case the downloaded files are
stored under data/spend_samples/ (ignored by git).
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://dea-data-bucket.s3.us-east-1.amazonaws.com/calendly_spend_data"
TIMEOUT = 30


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def fetch_json(url: str):
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def spend_file_names(index) -> list[str]:
    """The index format is not specified in the brief; accept a list of names, a list of
    objects with a name-like field, or an object holding such a list."""
    if isinstance(index, dict):
        for key in ("files", "file_names", "filenames", "keys", "objects"):
            if key in index:
                return spend_file_names(index[key])
        return sorted(k for k in index if str(k).endswith(".json"))
    names: list[str] = []
    for item in index:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            for key in ("file_name", "filename", "name", "key", "file"):
                if key in item:
                    names.append(str(item[key]))
                    break
    return sorted(n.rsplit("/", 1)[-1] for n in names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", action="store_true", help="save downloaded files")
    args = parser.parse_args()

    load_env()
    base_url = os.getenv("SPEND_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

    print(f"Index: {base_url}/file_index.json")
    try:
        index = fetch_json(f"{base_url}/file_index.json")
    except requests.RequestException as exc:
        print(f"  FAILED: {exc}")
        return 1
    print("  raw index (first 600 characters):")
    print("  " + json.dumps(index)[:600])

    names = spend_file_names(index)
    print(f"\nFiles listed: {len(names)}")
    for name in names[:5]:
        print(f"  {name}")
    if len(names) > 5:
        print(f"  ... {names[-1]}")
    if not names:
        print("  No file names recognized; inspect the raw index above.")
        return 1

    latest = names[-1]
    print(f"\nLatest file: {base_url}/{latest}")
    try:
        records = fetch_json(f"{base_url}/{latest}")
    except requests.RequestException as exc:
        print(f"  FAILED: {exc}")
        return 1

    dates = sorted({r["date"] for r in records})
    by_channel = Counter(r["channel"] for r in records)
    total = defaultdict(float)
    for r in records:
        total[r["channel"]] += float(r["spend"])
    print(f"  records: {len(records)}")
    print(f"  date range: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    print("  records per channel:", dict(by_channel))
    print("  spend per channel (USD):", {k: round(v, 2) for k, v in total.items()})
    pairs = Counter((r["date"], r["channel"]) for r in records)
    duplicates = [k for k, v in pairs.items() if v > 1]
    print(f"  duplicate (date, channel) pairs within the file: {len(duplicates)}")

    if args.save:
        out = Path("data/spend_samples")
        out.mkdir(parents=True, exist_ok=True)
        (out / "file_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
        (out / latest).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"\nSaved to {out}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
