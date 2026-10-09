"""Shared helper for reading GitHub Projects v2 board data via the `gh` CLI.
Read-only -- no check in this repo ever writes back to GitHub. Requires `gh`
on PATH, already authenticated (the same `gh auth` used interactively).
"""
import json
import subprocess

MIA_ANNOTATION_PROJECT = {"owner": "AI-HHMI", "number": "1"}
MIA_PRETRAINING_PROJECT = {"owner": "AI-HHMI", "number": "4"}


def fetch_project_items(owner: str, number: str, limit: int = 2000) -> list[dict]:
    """Return every item (with all board fields) on a GitHub Projects v2 board."""
    result = subprocess.run(
        ["gh", "project", "item-list", number, "--owner", owner, "--format", "json", "-L", str(limit)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"gh project item-list failed (owner={owner}, number={number}): {result.stderr.strip()}")
    data = json.loads(result.stdout)
    items = data.get("items", [])
    if data.get("totalCount", 0) > len(items):
        raise SystemExit(
            f"gh project item-list returned {len(items)} of {data['totalCount']} items -- "
            f"raise `limit` (currently {limit})"
        )
    return items
