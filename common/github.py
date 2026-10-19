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
# (network hiccup), not a real problem with the request itself -- worth a
# short retry. Rate limiting is handled separately below, since "rate limit"
# covers two very different real situations with identical wording from `gh`
# (confirmed on this project: the exact same "API rate limit exceeded for
# user ID ..." string came from both a few-second secondary/burst limit and,
# on an unattended weekend run_all_checks.py run, real primary-quota
# exhaustion that a 30s backoff can't fix -- it only resets on its own
# schedule, sometimes tens of minutes out).
_OTHER_TRANSIENT_SUBSTRINGS = ("unexpected eof", "timeout", "connection reset")
_RATE_LIMIT_SUBSTRING = "rate limit"

# Never wait longer than this for a real quota reset, even if `gh api
# rate_limit` reports more -- bounds worst-case delay in an unattended run.
_MAX_RATE_LIMIT_WAIT_SECONDS = 3900  # 65 min


def _rate_limit_wait_seconds():
    """None if there's still real GraphQL quota left (the failure was the
    transient secondary/burst limit, a short backoff is enough); otherwise
    the real number of seconds until quota resets (capped), queried live
    from `gh api rate_limit` rather than guessed -- the two situations are
    indistinguishable from the error message alone.
    """
    try:
        result = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        gql = json.loads(result.stdout)["resources"]["graphql"]
        if gql["remaining"] > 0:
            return None
        return max(0, min(gql["reset"] - time.time(), _MAX_RATE_LIMIT_WAIT_SECONDS)) + 5
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError):
        return None


def fetch_project_items(owner: str, number: str, limit: int = 2000, retries: int = 4) -> list[dict]:
    """Return every item (with all board fields) on a GitHub Projects v2 board.
    Retries a transient-looking `gh` failure (rate limit, network hiccup) a
    few times before raising -- a rate-limit failure's backoff is sized from
    the real live quota (see _rate_limit_wait_seconds), not a flat guess.
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
        is_last_attempt = attempt == retries - 1
        if not is_last_attempt and _RATE_LIMIT_SUBSTRING in last_stderr.lower():
            wait = _rate_limit_wait_seconds()
            time.sleep(30 if wait is None else wait)
            continue
        if not is_last_attempt and any(s in last_stderr.lower() for s in _OTHER_TRANSIENT_SUBSTRINGS):
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
