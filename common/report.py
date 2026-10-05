"""Shared JSON + HTML report writer for mia-data-qc checks.

Every check script calls write_check_report() with its findings; this keeps
the per-date index and the root index (dated links, newest first) in sync
without each check having to know about report layout.
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
    # Sidecar count, so the index pages never need to re-parse a (possibly huge) findings file.
    (date_dir / f"{check_name}.count").write_text(str(len(findings)))

    html_path = date_dir / f"{check_name}.html"
    html_path.write_text(_render_check_html(check_name, date, findings))

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


def _read_count(count_path: Path) -> int:
    try:
        return int(count_path.read_text().strip())
    except (OSError, ValueError):
        return 0


def _update_date_index(date_dir: Path, date: str) -> None:
    check_pages = sorted(p.name for p in date_dir.glob("*.html") if p.name != "index.html")
    items = "\n".join(
        '<li><a href="{page}">{name}</a> — {count} finding(s)</li>'.format(
            page=html.escape(p),
            name=html.escape(p[:-5]),
            count=_read_count(date_dir / f"{p[:-5]}.count"),
        )
        for p in check_pages
    )
    (date_dir / "index.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>QC reports — {date}</title></head>
<body>
<p><a href="../../qc_dashboard.html">&larr; all dates</a></p>
<h1>QC reports — {date}</h1>
<ul>
{items}
</ul>
</body></html>
""")


def _update_root_index(reports_dir: Path) -> None:
    dates = sorted((p.name for p in reports_dir.iterdir() if p.is_dir()), reverse=True)
    reports_dirname = reports_dir.name
    items = []
    for d in dates:
        date_dir = reports_dir / d
        total = sum(_read_count(p) for p in date_dir.glob("*.count"))
        items.append(
            '<li><a href="{reports}/{date}/index.html">{date}</a> — {total} finding(s) total</li>'.format(
                reports=html.escape(reports_dirname), date=html.escape(d), total=total,
            )
        )
    items_html = "\n".join(items)
    (reports_dir.parent / "qc_dashboard.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>mia-data-qc reports</title></head>
<body>
<h1>mia-data-qc — QC reports</h1>
<p>Latest run first.</p>
<ul>
{items_html}
</ul>
</body></html>
""")
