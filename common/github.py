"""Shared helper for reading GitHub Projects v2 board data via the `gh` CLI.
Read-only -- no check in this repo ever writes back to GitHub. Requires `gh`
on PATH, already authenticated (the same `gh auth` used interactively).
"""
import json
import subprocess
import time

MIA_ANNOTATION_PROJECT = {"owner": "AI-HHMI", "number": "1"}
MIA_PRETRAINING_PROJECT = {"owner": "AI-HHMI", "number": "4"}

# Substrings seen in real `gh` CLI failures on this project that are transient
# (network hiccup or GitHub's secondary/burst rate limit), not a real problem
# with the request itself -- worth a few retries before giving up. Found via
# an overnight unattended run_all_checks.py run that crashed on "unexpected
# EOF" with nobody around to notice and retry by hand.
_TRANSIENT_ERROR_SUBSTRINGS = ("rate limit", "unexpected eof", "timeout", "connection reset")


def fetch_project_items(owner: str, number: str, limit: int = 2000, retries: int = 4) -> list[dict]:
    """Return every item (with all board fields) on a GitHub Projects v2 board.
    Retries a transient-looking `gh` failure (rate limit, network hiccup) a
    few times with a short backoff before raising.
    """
    last_stderr = ""
    for attempt in range(retries):
        result = subprocess.run(
            ["gh", "project", "item-list", number, "--owner", owner, "--format", "json", "-L", str(limit)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            break
        last_stderr = result.stderr.strip()
        if attempt < retries - 1 and any(s in last_stderr.lower() for s in _TRANSIENT_ERROR_SUBSTRINGS):
            time.sleep(30)
            continue
        raise SystemExit(f"gh project item-list failed (owner={owner}, number={number}): {last_stderr}")

    data = json.loads(result.stdout)
    items = data.get("items", [])
    if data.get("totalCount", 0) > len(items):
        raise SystemExit(
            f"gh project item-list returned {len(items)} of {data['totalCount']} items -- "
            f"raise `limit` (currently {limit})"
        )
    return items
