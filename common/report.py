"""Shared JSON + HTML + Markdown report writer for mia-data-qc checks.

Every check script calls write_check_report() with its findings; this keeps
the per-date index and the root index (dated links, newest first) in sync
without each check having to know about report layout.

Three files per check: {check}.json (the real artifact -- what an LLM triage
pass reads directly), {check}.html (our own hand-written, styled rendering --
served as a real page now that GitHub Pages is live on this repo, Oct 6 2026;
generated directly by this script, not produced by GitHub Pages' Jekyll
md-to-html auto-conversion, so styling/structure stays fully under our
control), and {check}.md (renders natively in GitHub's own repo blob view too,
useful when just browsing the repo instead of the Pages site). Counts are read
straight from each check's own JSON -- cheap now that a check surfacing a huge
findings list gets its root cause fixed instead of needing a special-cased
summary path (see ownership_permissions, Oct 5-6 2026).
"""
import datetime
import html
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

    html_path = date_dir / f"{check_name}.html"
    html_path.write_text(_render_check_html(check_name, date, findings))

    md_path = date_dir / f"{check_name}.md"
    md_path.write_text(_render_check_md(check_name, date, findings))

    _update_date_index(date_dir, date)
    _update_root_index(reports_dir)
    return html_path


def _render_check_html(check_name: str, date: str, findings: list[dict]) -> str:
    rows = "\n".join(
        "<tr><td>{dataset}</td><td>{path}</td><td>{field}</td><td>{actual}</td>"
        "<td>{expected}</td><td class=sev-{severity}>{severity}</td><td>{fix}</td></tr>".format(
            dataset=html.escape(str(f.get("dataset", ""))),
            path=html.escape(str(f.get("path", ""))),
            field=html.escape(str(f.get("field", ""))),
            actual=html.escape(str(f.get("actual", ""))),
            expected=html.escape(str(f.get("expected", ""))),
            severity=html.escape(str(f.get("severity", "error"))),
            fix=html.escape(str(f.get("suggested_fix", ""))),
        )
        for f in findings
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(check_name)} — {date}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; font-size: 0.9em; }}
th {{ background: #eee; }}
.sev-error {{ color: #b00; font-weight: bold; }}
.sev-warning {{ color: #a60; }}
</style></head>
<body>
<p><a href="index.html">&larr; {date}</a></p>
<h1>{html.escape(check_name)}</h1>
<p>{len(findings)} finding(s) on {date}.</p>
<table><tr><th>Dataset</th><th>Path</th><th>Field</th><th>Actual</th><th>Expected</th><th>Severity</th><th>Suggested fix</th></tr>
{rows}
</table>
</body></html>
"""


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
    check_names = sorted(p.stem for p in date_dir.glob("*.html") if p.stem != "index")

    html_items = "\n".join(
        '<li><a href="{name}.html">{name}</a> — {count} finding(s)</li>'.format(
            name=html.escape(name), count=_count_findings(date_dir / f"{name}.json"),
        )
        for name in check_names
    )
    (date_dir / "index.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>QC reports — {date}</title></head>
<body>
<p><a href="../../qc_dashboard.html">&larr; all dates</a></p>
<h1>QC reports — {date}</h1>
<ul>
{html_items}
</ul>
</body></html>
""")

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
    html_items = []
    md_items = []
    for d in dates:
        date_dir = reports_dir / d
        total = sum(_count_findings(p) for p in date_dir.glob("*.json"))
        html_items.append(
            '<li><a href="{reports}/{date}/index.html">{date}</a> — {total} finding(s) total</li>'.format(
                reports=html.escape(reports_dirname), date=html.escape(d), total=total,
            )
        )
        md_items.append(f"- [{d}]({reports_dirname}/{d}/index.md) — {total} finding(s) total")

    html_items_s = "\n".join(html_items)
    (reports_dir.parent / "qc_dashboard.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>mia-data-qc reports</title></head>
<body>
<h1>mia-data-qc — QC reports</h1>
<p>Latest run first.</p>
<ul>
{html_items_s}
</ul>
</body></html>
""")

    md_items_s = "\n".join(md_items)
    (reports_dir.parent / "qc_dashboard.md").write_text(f"""# mia-data-qc reports

Latest run first.

{md_items_s}
""")
