"""Shared JSON + Markdown report writer for mia-data-qc checks.

Every check script calls write_check_report() with its findings; this keeps
the per-date index and the root index (dated links, newest first) in sync
without each check having to know about report layout.

Two files per check: {check}.json (the real artifact -- what an LLM triage
pass reads directly) and {check}.md (a rendered view -- GitHub renders .md
natively in its own private-repo blob view, unlike .html, which GitHub never
executes; see lmvd_quality_control.md's Oct 6 2026 history. HTML reports were
tried first and dropped the same day once Markdown was confirmed to work).
Counts are read straight from each check's own JSON -- cheap now that a check
surfacing a huge findings list gets its root cause fixed instead of needing a
special-cased summary path (see ownership_permissions, Oct 5-6 2026).
"""
import datetime
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_check_report(check_name: str, findings: list[dict], reports_dir: Path = None, date: str = None) -> Path:
    reports_dir = (reports_dir or REPO_ROOT / "reports").resolve()
    date = date or datetime.date.today().isoformat()
    date_dir = reports_dir / date
    date_dir.mkdir(parents=True, exist_ok=True)

    json_path = date_dir / f"{check_name}.json"
    json_path.write_text(json.dumps({"check": check_name, "date": date, "findings": findings}, indent=2))

    md_path = date_dir / f"{check_name}.md"
    md_path.write_text(_render_check_md(check_name, date, findings))

    _update_date_index(date_dir, date)
    _update_root_index(reports_dir)
    return md_path


def _md_cell(value) -> str:
    # Escape pipes/newlines so a value can't break the markdown table structure.
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_check_md(check_name: str, date: str, findings: list[dict]) -> str:
    rows = "\n".join(
        "| {dataset} | {path} | {field} | {actual} | {expected} | {severity} | {fix} |".format(
            dataset=_md_cell(f.get("dataset", "")),
            path=_md_cell(f.get("path", "")),
            field=_md_cell(f.get("field", "")),
            actual=_md_cell(f.get("actual", "")),
            expected=_md_cell(f.get("expected", "")),
            severity=_md_cell(f.get("severity", "error")),
            fix=_md_cell(f.get("suggested_fix", "")),
        )
        for f in findings
    )
    table = (
        "| Dataset | Path | Field | Actual | Expected | Severity | Suggested fix |\n"
        "|---|---|---|---|---|---|---|\n" + rows
        if findings else "No findings."
    )
    return f"""# {check_name} — {date}

[← {date}](index.md)

{len(findings)} finding(s) on {date}.

{table}
"""


def _count_findings(json_path: Path) -> int:
    try:
        return len(json.loads(json_path.read_text()).get("findings", []))
    except (OSError, json.JSONDecodeError):
        return 0


def _update_date_index(date_dir: Path, date: str) -> None:
    check_names = sorted(p.stem for p in date_dir.glob("*.md") if p.stem != "index")

    md_items = "\n".join(
        "- [{name}]({name}.md) — {count} finding(s)".format(
            name=name, count=_count_findings(date_dir / f"{name}.json"),
        )
        for name in check_names
    )
    (date_dir / "index.md").write_text(f"""# QC reports — {date}

[← all dates](../../qc_dashboard.md)

{md_items}
""")


def _update_root_index(reports_dir: Path) -> None:
    dates = sorted((p.name for p in reports_dir.iterdir() if p.is_dir()), reverse=True)
    reports_dirname = reports_dir.name
    md_items = []
    for d in dates:
        date_dir = reports_dir / d
        total = sum(_count_findings(p) for p in date_dir.glob("*.json"))
        md_items.append(f"- [{d}]({reports_dirname}/{d}/index.md) — {total} finding(s) total")

    md_items_s = "\n".join(md_items)
    (reports_dir.parent / "qc_dashboard.md").write_text(f"""# mia-data-qc reports

Latest run first.

{md_items_s}
""")
