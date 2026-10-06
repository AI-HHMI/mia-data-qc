"""Shared JSON + HTML report writer for mia-data-qc checks.

Every check script calls write_check_report() with its findings; this keeps
the per-date index and the root index (dated links, newest first) in sync
without each check having to know about report layout.

Two files per check: {check}.json (the real artifact -- what an LLM triage
pass reads directly) and {check}.html (our own hand-written, styled rendering,
generated directly by this script -- served as a real page via GitHub Pages,
live on this public repo since Oct 6 2026). Counts are read straight from each
check's own JSON -- cheap now that a check surfacing a huge findings list gets
its root cause fixed instead of needing a special-cased summary path (see
ownership_permissions, Oct 5-6 2026).
"""
import datetime
import html
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --ink:#14181f; --muted:#5d6675; --line:#e3e6eb;
  --head:#f1f3f6; --hover:#f5f8ff; --accent:#2557d6; --accent-soft:#e8eefc;
  --err:#b00020; --err-soft:#fbe9e9; --warn:#9a6400; --warn-soft:#fff4e0;
  --shadow:0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08); }
@media (prefers-color-scheme: dark) { :root { --bg:#0e1116; --card:#161b22; --ink:#e6e9ee;
  --muted:#9aa4b2; --line:#262d38; --head:#1b212b; --hover:#1a2230; --accent:#7aa2ff;
  --accent-soft:#1b2842; --err:#ff6b6b; --err-soft:#3a1f1f; --warn:#ffb86b; --warn-soft:#3a2e1a;
  --shadow:none; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
.wrap { max-width:1400px; margin:0 auto; padding:28px 24px 56px; }
.nav { margin-bottom:18px; }
h1 { margin:0 0 4px; font-size:24px; font-weight:700; letter-spacing:-.02em; }
.sub { color:var(--muted); margin:0 0 24px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); }
.scroll { overflow:auto; max-height:75vh; border-radius:12px; }
table { border-collapse:separate; border-spacing:0; width:100%; }
th, td { padding:10px 14px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }
th { position:sticky; top:0; z-index:1; background:var(--head); color:var(--muted);
  font-size:12px; font-weight:600; letter-spacing:.02em; cursor:pointer; user-select:none; }
th:hover { color:var(--ink); }
th.asc::after { content:" \\25B2"; font-size:9px; }
th.desc::after { content:" \\25BC"; font-size:9px; }
tbody tr:hover td { background:var(--hover); }
tbody tr:last-child td { border-bottom:0; }
.chip { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
.chip.error { color:var(--err); background:var(--err-soft); }
.chip.warning { color:var(--warn); background:var(--warn-soft); }
ul.list { list-style:none; margin:0; padding:0; display:grid; gap:10px; }
ul.list li { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 16px; }
ul.list .count { color:var(--muted); font-size:12.5px; }
.empty { color:var(--muted); padding:16px; }
"""

_SORT_JS = """
document.querySelectorAll('table.sortable').forEach(function (table) {
  table.querySelectorAll('th').forEach(function (th, idx) {
    th.addEventListener('click', function () {
      var tbody = table.querySelector('tbody');
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      var asc = !th.classList.contains('asc');
      table.querySelectorAll('th').forEach(function (h) { h.classList.remove('asc', 'desc'); });
      th.classList.add(asc ? 'asc' : 'desc');
      rows.sort(function (a, b) {
        var av = a.children[idx].innerText, bv = b.children[idx].innerText;
        return asc ? av.localeCompare(bv, undefined, {numeric: true})
                    : bv.localeCompare(av, undefined, {numeric: true});
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
});
"""


def write_check_report(check_name: str, findings: list[dict], reports_dir: Path = None, date: str = None) -> Path:
    reports_dir = (reports_dir or REPO_ROOT / "reports").resolve()
    date = date or datetime.date.today().isoformat()
    date_dir = reports_dir / date
    date_dir.mkdir(parents=True, exist_ok=True)

    json_path = date_dir / f"{check_name}.json"
    json_path.write_text(json.dumps({"check": check_name, "date": date, "findings": findings}, indent=2))

    html_path = date_dir / f"{check_name}.html"
    html_path.write_text(_render_check_html(check_name, date, findings))

    _update_date_index(date_dir, date)
    _update_root_index(reports_dir)
    return html_path


def _render_check_html(check_name: str, date: str, findings: list[dict]) -> str:
    if findings:
        rows = "\n".join(
            "<tr><td>{dataset}</td><td>{path}</td><td>{field}</td><td>{actual}</td>"
            "<td>{expected}</td><td><span class=\"chip {severity}\">{severity}</span></td><td>{fix}</td></tr>".format(
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
        body = f"""<div class="card scroll">
<table class="sortable"><thead><tr><th>Dataset</th><th>Path</th><th>Field</th><th>Actual</th>
<th>Expected</th><th>Severity</th><th>Suggested fix</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>"""
    else:
        body = '<div class="card empty">No findings.</div>'

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(check_name)} — {date}</title>
<style>{_STYLE}</style></head>
<body><div class="wrap">
<p class="nav"><a href="index.html">&larr; {date}</a></p>
<h1>{html.escape(check_name)}</h1>
<p class="sub">{len(findings)} finding(s) on {date}.</p>
{body}
</div>
<script>{_SORT_JS}</script>
</body></html>
"""


def _count_findings(json_path: Path) -> int:
    try:
        return len(json.loads(json_path.read_text()).get("findings", []))
    except (OSError, json.JSONDecodeError):
        return 0


def _update_date_index(date_dir: Path, date: str) -> None:
    check_names = sorted(p.stem for p in date_dir.glob("*.html") if p.stem != "index")
    items = "\n".join(
        '<li><a href="{name}.html">{name}</a> <span class="count">— {count} finding(s)</span></li>'.format(
            name=html.escape(name), count=_count_findings(date_dir / f"{name}.json"),
        )
        for name in check_names
    )
    (date_dir / "index.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>QC reports — {date}</title>
<style>{_STYLE}</style></head>
<body><div class="wrap">
<p class="nav"><a href="../../qc_dashboard.html">&larr; all dates</a></p>
<h1>QC reports — {date}</h1>
<ul class="list">
{items}
</ul>
</div></body></html>
""")


def _update_root_index(reports_dir: Path) -> None:
    dates = sorted((p.name for p in reports_dir.iterdir() if p.is_dir()), reverse=True)
    reports_dirname = reports_dir.name
    items = []
    for d in dates:
        date_dir = reports_dir / d
        total = sum(_count_findings(p) for p in date_dir.glob("*.json"))
        items.append(
            '<li><a href="{reports}/{date}/index.html">{date}</a> '
            '<span class="count">— {total} finding(s) total</span></li>'.format(
                reports=html.escape(reports_dirname), date=html.escape(d), total=total,
            )
        )
    items_html = "\n".join(items)
    (reports_dir.parent / "qc_dashboard.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>mia-data-qc reports</title>
<style>{_STYLE}</style></head>
<body><div class="wrap">
<h1>mia-data-qc — QC reports</h1>
<p class="sub">Latest run first.</p>
<ul class="list">
{items_html}
</ul>
</div></body></html>
""")
