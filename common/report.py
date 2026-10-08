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
import collections
import datetime
import html
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# One-line description per check, shown on the dashboard, date index, and the
# check's own page. Missing entries just show no description -- never required.
CHECK_DESCRIPTIONS = {
    "ownership_permissions": "Every file/dir under data/ is group miaai, group-read, group-execute, no group-write.",
    "dataset_naming": "{modality}-{organism}-{dataset} against the canonical vocab, PyTC-casing rule.",
    "label_naming": "{provenance}-{label_class}-{specific_info} for every label directory.",
    "crop_naming": "crop-NNN.zarr or crop-NNN_descriptor.zarr for every crop store.",
    "stray_files": ".DS_Store anywhere, job-output junk leftover in labels/.",
    "pyramid_consistency": "Each zarr.json's multiscales.datasets list matches pyramid levels that exist on disk.",
    "metadata_consistency": "A label's directory-name-derived provenance/label_class agrees with its stored metadata.",
    "metadata_vocab": "A label's segmentation_type/proofreading_status/coverage match the canonical enums.",
    "voxel_size": "Raw's voxel size isn't a placeholder; each label's voxel size aligns with raw's pyramid.",
    "metadata_completeness": "Every label's zarr.json has all 12 required metadata fields present.",
    "bbox_sanity": "A label's bbox has a valid coordinate_order/unit and a structurally sane offset/size.",
    "chunk_shard_sanity": "Every sharded array's shard shape is an exact multiple of its own chunk shape.",
    "license_fields": "Every crop has a license field present on both its root zarr.json and raw/zarr.json.",
    "multitc_naming": "A crop with more than one timepoint/channel in its raw array encodes that as {N}t_{M}c in its descriptor.",
    "parent_raw_validity": "A label's parent_raw field (when present) points to a directory that actually exists.",
    "channel_index_consistency": "A label derived from one channel of a multi-channel raw records a valid source.channel_index.",
}

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
.wrap { max-width:1400px; margin:0 auto; padding:0 24px; }
header.site { background:var(--card); border-bottom:1px solid var(--line); margin-bottom:28px; }
header.site .wrap { padding:16px 24px; display:flex; align-items:center; justify-content:space-between; }
header.site .brand { font-weight:700; font-size:15px; letter-spacing:-.01em; }
header.site nav a { margin-left:16px; color:var(--muted); font-size:13px; }
header.site nav a:hover { color:var(--accent); }
main.wrap { padding-bottom:56px; }
.nav-back { margin-bottom:14px; display:inline-block; font-size:13px; }
h1 { margin:0 0 4px; font-size:24px; font-weight:700; letter-spacing:-.02em; }
.sub { color:var(--muted); margin:0 0 24px; max-width:70ch; }
.summary { display:flex; gap:10px; margin-bottom:20px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:10px 16px; box-shadow:var(--shadow); }
.stat .n { font-size:20px; font-weight:700; }
.stat .l { color:var(--muted); font-size:12px; }
.stat.error .n { color:var(--err); }
.stat.warning .n { color:var(--warn); }
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
.grid, .tabs { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; margin-bottom:20px; }
a.tile { display:flex; flex-direction:column; gap:6px; padding:14px 16px; border:1px solid var(--line);
  border-radius:12px; background:var(--card); color:var(--ink); box-shadow:var(--shadow); }
a.tile:hover { border-color:var(--accent); text-decoration:none; }
a.tile .name { font-weight:650; font-size:14.5px; overflow-wrap:anywhere; }
a.tile .desc { color:var(--muted); font-size:12.5px; overflow-wrap:anywhere; }
a.tile .badge { align-self:flex-start; }
.tabs a.tile.on { border-color:var(--accent); background:var(--accent-soft); box-shadow:0 0 0 1px var(--accent); }
.panel[hidden] { display:none; }
.panel h2 { margin:0 0 4px; font-size:18px; }
.empty { color:var(--muted); padding:16px; }
footer.site { color:var(--muted); font-size:12px; padding:24px 0 40px; text-align:center; }
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

_TABS_JS = """
function mdqSelectTab(id) {
  document.querySelectorAll('.tabs a.tile').forEach(function (t) {
    t.classList.toggle('on', t.getAttribute('href') === '#' + id);
  });
  document.querySelectorAll('.panel').forEach(function (p) { p.hidden = (p.id !== id); });
}
document.querySelectorAll('.tabs a.tile').forEach(function (tab) {
  tab.addEventListener('click', function (e) {
    e.preventDefault();
    var id = tab.getAttribute('href').slice(1);
    mdqSelectTab(id);
    history.replaceState(null, '', '#' + id);
  });
});
(function () {
  var first = document.querySelector('.panel');
  var id = (location.hash || '').slice(1);
  if (!document.getElementById(id)) { id = first ? first.id : ''; }
  if (id) { mdqSelectTab(id); }
})();
"""


def _page(title: str, home_href: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_STYLE}</style></head>
<body>
<header class="site"><div class="wrap">
<a class="brand" href="{home_href}">mia-data-qc</a>
<nav><a href="https://github.com/AI-HHMI/mia-data-qc">GitHub</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="site">mia-data-qc &middot; automated QC for the LMD corpus</footer>
<script>{script}</script>
</body></html>
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


def _render_check_section(check_name: str, findings: list[dict]) -> str:
    """The summary stats + table for one check -- shared by the standalone
    per-check page and the tabbed panel embedded in the date index.
    """
    counts = collections.Counter(f.get("severity", "error") for f in findings)
    summary = "".join(
        f'<div class="stat {sev}"><div class="n">{counts[sev]}</div><div class="l">{sev}</div></div>'
        for sev in ("error", "warning") if counts[sev]
    ) or '<div class="stat"><div class="n">0</div><div class="l">findings</div></div>'

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
        table = f"""<div class="card scroll">
<table class="sortable"><thead><tr><th>Dataset</th><th>Path</th><th>Field</th><th>Actual</th>
<th>Expected</th><th>Severity</th><th>Suggested fix</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>"""
    else:
        table = '<div class="card empty">No findings.</div>'

    return f'<div class="summary">{summary}</div>\n{table}'


def _render_check_html(check_name: str, date: str, findings: list[dict]) -> str:
    description = CHECK_DESCRIPTIONS.get(check_name, "")
    section = _render_check_section(check_name, findings)
    body = f"""<a class="nav-back" href="index.html">&larr; {date}</a>
<h1>{html.escape(check_name)}</h1>
<p class="sub">{html.escape(description)}</p>
{section}"""
    return _page(f"{check_name} — {date}", "../../qc_dashboard.html", body, _SORT_JS)


def _load_findings(json_path: Path) -> list[dict]:
    try:
        return json.loads(json_path.read_text()).get("findings", [])
    except (OSError, json.JSONDecodeError):
        return []


def _count_findings(json_path: Path) -> int:
    return len(_load_findings(json_path))


def _update_date_index(date_dir: Path, date: str) -> None:
    check_names = sorted(p.stem for p in date_dir.glob("*.json"))

    tabs = []
    panels = []
    for i, name in enumerate(check_names):
        findings = _load_findings(date_dir / f"{name}.json")
        count = len(findings)
        tabs.append(
            '<a class="tile" href="#{name}"><span class="name">{name}</span>'
            '<span class="desc">{desc}</span>'
            '<span class="badge chip {sev}">{count} finding(s)</span></a>'.format(
                name=html.escape(name), desc=html.escape(CHECK_DESCRIPTIONS.get(name, "")),
                count=count, sev="error" if count else "",
            )
        )
        panels.append(
            '<section id="{name}" class="panel"{hidden}><h2>{name}</h2>'
            '<p class="sub">{desc}</p>{section}</section>'.format(
                name=html.escape(name), hidden="" if i == 0 else " hidden",
                desc=html.escape(CHECK_DESCRIPTIONS.get(name, "")),
                section=_render_check_section(name, findings),
            )
        )

    body = f"""<a class="nav-back" href="../../qc_dashboard.html">&larr; all dates</a>
<h1>QC reports — {date}</h1>
<p class="sub">Click a check to see its findings below.</p>
<div class="tabs">
{chr(10).join(tabs)}
</div>
{chr(10).join(panels)}"""
    (date_dir / "index.html").write_text(
        _page(f"QC reports — {date}", "../../qc_dashboard.html", body, _SORT_JS + _TABS_JS)
    )


def _update_root_index(reports_dir: Path) -> None:
    dates = sorted((p.name for p in reports_dir.iterdir() if p.is_dir()), reverse=True)
    reports_dirname = reports_dir.name
    tiles = []
    for d in dates:
        date_dir = reports_dir / d
        total = sum(_count_findings(p) for p in date_dir.glob("*.json"))
        n_checks = len(list(date_dir.glob("*.json")))
        tiles.append(
            '<a class="tile" href="{reports}/{date}/index.html"><span class="name">{date}</span>'
            '<span class="desc">{n_checks} check(s) run</span>'
            '<span class="badge chip {sev}">{total} finding(s)</span></a>'.format(
                reports=html.escape(reports_dirname), date=html.escape(d), n_checks=n_checks,
                total=total, sev="error" if total else "",
            )
        )
    tiles_html = "\n".join(tiles)
    body = f"""<h1>mia-data-qc</h1>
<p class="sub">Automated QC checks over the LMD data corpus
(<code>/groups/miaai/miaai/lmd-v0.0.1/data</code>), run on the Janelia cluster. Latest run first.</p>
<div class="grid">
{tiles_html}
</div>"""
    (reports_dir.parent / "qc_dashboard.html").write_text(_page("mia-data-qc reports", "qc_dashboard.html", body))
