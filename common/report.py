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
import os.path
from pathlib import Path
from urllib.parse import quote

# Fileglancer's `/browse/<path>` URLs are plain path-based (unlike its
# auth-gated `/files/<key>/` proxied kind) -- this is the one literal zone
# prefix every real board Fileglancer_Path on this corpus uses, confirmed by
# survey, so it's reconstructible directly from a finding's own relative
# path with no API call.
FILEGLANCER_PREFIX = "https://fileglancer.int.janelia.org/browse/groups_miaai_miaai/lmd-v0.0.1/data/"


def _fileglancer_url(rel_path: str) -> str:
    return FILEGLANCER_PREFIX + quote(rel_path)


def _looks_like_folder(rel_path: str) -> bool:
    """True unless rel_path's last real segment looks like a file (has a
    "." extension and isn't itself a .zarr store, which is a directory
    despite the dot) -- used to decide whether a path is worth a
    Fileglancer link at all (individual files aren't, folders are). A path
    carrying trailing prose (e.g. "... (label_class)", seen on
    divergent_voxel_counts's grouped path) isn't a real filesystem path
    either, so it's excluded the same way.
    """
    if not rel_path or " (" in rel_path:
        return False
    last = rel_path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in last or last.endswith(".zarr")


def _fileglancer_link(rel_path: str, label_html: str) -> str:
    if not _looks_like_folder(rel_path):
        return label_html
    return f'<a href="{html.escape(_fileglancer_url(rel_path))}" target="_blank" rel="noopener">{label_html}</a>'

REPO_ROOT = Path(__file__).resolve().parent.parent

# One-line description per check, shown on the dashboard, date index, and the
# check's own page. Missing entries just show no description -- never required.
CHECK_DESCRIPTIONS = {
    "ownership_permissions": "Every file/dir under data/ is group miaai, group-read, group-execute, no group-write.",
    "dataset_naming": "Every dataset's folder name follows the standard pattern (modality-organism-dataset) and uses approved terms.",
    "label_naming": "{provenance}-{label_class}-{specific_info} for every label directory.",
    "crop_naming": "Every crop's folder name follows the standard crop-NNN pattern.",
    "stray_files": "Flags leftover junk (.DS_Store files, old job logs) that shouldn't be sitting inside the data folders.",
    "pyramid_consistency": "Each zarr.json's multiscales.datasets list matches pyramid levels that exist on disk.",
    "metadata_consistency": "A label's directory-name-derived provenance/label_class agrees with its stored metadata.",
    "metadata_vocab": "A label's segmentation type, proofreading status, and coverage use only approved, recognized values.",
    "voxel_size": "Raw's voxel size isn't a placeholder; each label's voxel size aligns with raw's pyramid.",
    "metadata_completeness": "Every label's zarr.json has all 12 required metadata fields present.",
    "bbox_sanity": "A label's bbox has a valid coordinate_order/unit and a structurally sane offset/size.",
    "chunk_shard_sanity": "Every sharded array's shard shape is an exact multiple of its own chunk shape.",
    "license_fields": "Every crop has a license field present on both its root zarr.json and raw/zarr.json.",
    "multitc_naming": "A crop with more than one timepoint/channel in its raw array encodes that as {N}t_{M}c in its descriptor.",
    "parent_raw_validity": "A label's parent_raw field (when present) points to a directory that actually exists.",
    "channel_index_consistency": "A label pulled from one channel of a multi-channel image correctly records which channel it came from.",
    "multitimepoint_label_sparsity": "A single-timepoint label is sized to match the full time series but only has actual content where it's supposed to -- at its one timepoint.",
    "label_field_drift": "A label's tracking issue on GitHub shows the same info as what's actually stored with the label on disk.",
    "label_orphaned_ingest": "Every real label has a GitHub issue tracking it, and every GitHub issue marked done actually has real data behind it.",
    "empty_label_data": "A label with complete metadata actually has chunk data written at its finest pyramid level.",
    "freshness": "A label's creation date is valid, and when multiple versions of the same label exist, the one marked \"current\" really is the newest.",
    "dataset_field_drift": "A dataset's tracking issue on GitHub shows the same axis order and data type as what's actually on disk.",
    "dataset_orphaned_ingest": "Every real dataset has at least one GitHub issue tracking it.",
    "divergent_voxel_counts": "Two different versions of the same labeled region (e.g. a manual annotation vs. an automated one) have wildly different amounts of annotated data -- worth a second look.",
    "annotated_voxels_sanity": "A label's annotated data can't be bigger than the image it's supposed to fit inside -- flags it if the numbers don't add up.",
    "label_disk_usage_sanity": "Flags a label's folder if its disk footprint looks abnormal compared to every other folder on the corpus -- a sign something's corrupted or unusual.",
    "dataset_disk_usage_sanity": "Flags a dataset's folders if their disk footprint looks abnormal compared to every other folder on the corpus -- a sign something's corrupted or unusual.",
    "dataset_crop_coverage": "Every crop in a multi-crop dataset is tracked by a GitHub issue -- either its own, or one covering the whole dataset.",
}

# Groups checks by what they actually validate, for the dashboard and README --
# purely a display grouping, doesn't change how any check runs. A check not
# listed here falls into "Uncategorized" rather than silently disappearing
# from the grouped view (see _UNCATEGORIZED_LABEL below).
_UNCATEGORIZED_LABEL = "Uncategorized"
CHECK_CATEGORIES = {
    "Filesystem & permissions": [
        "ownership_permissions", "stray_files", "label_disk_usage_sanity", "dataset_disk_usage_sanity",
    ],
    "Naming conventions": [
        "dataset_naming", "label_naming", "crop_naming", "multitc_naming",
    ],
    "Zarr structure validity": [
        "pyramid_consistency", "metadata_consistency", "chunk_shard_sanity", "parent_raw_validity",
        "channel_index_consistency", "multitimepoint_label_sparsity", "empty_label_data", "bbox_sanity",
    ],
    "Metadata content & vocabulary": [
        "metadata_vocab", "metadata_completeness", "voxel_size", "license_fields", "freshness",
    ],
    "Board vs. disk": [
        "label_field_drift", "dataset_field_drift", "label_orphaned_ingest", "dataset_orphaned_ingest",
        "dataset_crop_coverage",
    ],
    "Pixel-data sanity": [
        "divergent_voxel_counts", "annotated_voxels_sanity",
    ],
}


def _grouped_check_names(check_names: list[str]) -> list[tuple[str, list[str]]]:
    """[(category, [check_name, ...]), ...] covering exactly check_names --
    category order and within-category order from CHECK_CATEGORIES; anything
    in check_names but not in CHECK_CATEGORIES lands in one trailing
    "Uncategorized" group instead of being dropped.
    """
    remaining = set(check_names)
    groups = []
    for category, names in CHECK_CATEGORIES.items():
        present = [n for n in names if n in remaining]
        if present:
            groups.append((category, present))
            remaining -= set(present)
    if remaining:
        groups.append((_UNCATEGORIZED_LABEL, sorted(remaining)))
    return groups

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
header.site nav .updated { color:var(--muted); font-size:13px; }
main.wrap { padding-bottom:56px; }
.nav-back { margin-bottom:14px; display:inline-block; font-size:13px; }
h1 { margin:0 0 4px; font-size:24px; font-weight:700; letter-spacing:-.02em; }
.sub { color:var(--muted); margin:0 0 24px; max-width:70ch; }
.cat-heading { margin:28px 0 10px; font-size:13px; font-weight:700; text-transform:uppercase;
  letter-spacing:.04em; color:var(--muted); }
.cat-heading:first-of-type { margin-top:4px; }
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

def _page(title: str, home_href: str, body: str, script: str = "", last_refreshed: str = "") -> str:
    updated = f'<span class="updated">Last refreshed: {html.escape(last_refreshed)}</span>' if last_refreshed else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_STYLE}</style></head>
<body>
<header class="site"><div class="wrap">
<a class="brand" href="{home_href}">mia-data-qc</a>
<nav>{updated}<a href="https://github.com/AI-HHMI/mia-data-qc">GitHub</a></nav>
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


def _row_html(dataset: str, path_html: str, field: str, actual: str, expected: str,
               severity: str, fix: str) -> str:
    return (
        "<tr><td>{dataset}</td><td>{path}</td><td>{field}</td><td>{actual}</td>"
        "<td>{expected}</td><td><span class=\"chip {severity}\">{severity}</span></td><td>{fix}</td></tr>"
    ).format(
        dataset=html.escape(dataset), path=path_html, field=html.escape(field),
        actual=html.escape(actual), expected=html.escape(expected),
        severity=html.escape(severity), fix=html.escape(fix),
    )


# A table row collapses a group of findings into one when 3+ share an
# identical "story" (same dataset/field/actual/expected, differing only by
# path and possibly the fix text -- e.g. ownership_permissions bakes the
# literal path into its own suggested_fix, so that's never part of the group
# key) -- e.g. 557 ownership_permissions findings that are really just 4
# distinct incidents. This is purely a rendering choice: the underlying
# JSON stays one entry per real violation, every path is still listed (in
# the row's expandable detail, each linked to Fileglancer), and a check's
# own scan logic is completely unaffected -- it still finds and records
# everything.
_GROUP_MIN_SIZE = 3


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
        groups = {}
        order = []
        for f in findings:
            key = (
                str(f.get("dataset", "")), str(f.get("field", "")),
                str(f.get("actual", "")), str(f.get("expected", "")),
            )
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(f)

        row_htmls = []
        for key in order:
            dataset, field, actual, expected = key
            members = groups[key]
            severity = str(members[0].get("severity", "error"))
            fixes = {str(m.get("suggested_fix", "")) for m in members}

            if len(members) >= _GROUP_MIN_SIZE:
                paths = [str(m.get("path", "")) for m in members]
                try:
                    common = os.path.commonpath(paths)
                except ValueError:
                    common = dataset
                if len(fixes) == 1:
                    fix = next(iter(fixes))
                    items = "".join(
                        f"<li>{_fileglancer_link(p, html.escape(p))}</li>" for p in paths
                    )
                else:
                    fix = f"{len(fixes)} different fixes -- see each path below"
                    items = "".join(
                        f"<li>{_fileglancer_link(p, html.escape(p))} &mdash; "
                        f"{html.escape(str(m.get('suggested_fix', '')))}</li>"
                        for p, m in zip(paths, members)
                    )
                common_link = _fileglancer_link(common, f"<code>{html.escape(common)}</code>")
                path_html = (
                    f'<details><summary>{len(members)} paths under {common_link}</summary>'
                    f'<ul>{items}</ul></details>'
                )
                row_htmls.append(_row_html(dataset, path_html, field, actual, expected, severity, fix))
            else:
                for m in members:
                    path_str = str(m.get("path", ""))
                    path_html = _fileglancer_link(path_str, html.escape(path_str))
                    fix = str(m.get("suggested_fix", ""))
                    row_htmls.append(_row_html(dataset, path_html, field, actual, expected, severity, fix))

        table = f"""<div class="card scroll">
<table class="sortable"><thead><tr><th>Dataset</th><th>Path</th><th>Field</th><th>Actual</th>
<th>Expected</th><th>Severity</th><th>Suggested fix</th></tr></thead>
<tbody>
{chr(10).join(row_htmls)}
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
    """Each tile links straight to that check's own standalone page
    ({name}.html, already written by write_check_report) rather than
    embedding every check's findings table in this one page -- a check with
    a huge findings table (ownership_permissions has hit 80+ MB before) used
    to bloat this index for every visitor even if they wanted a different
    check. The index itself now only ever holds the small tile grid.
    """
    check_names = sorted(p.stem for p in date_dir.glob("*.json"))
    groups = _grouped_check_names(check_names)

    tab_groups = []
    for category, names in groups:
        tiles = []
        for name in names:
            count = _count_findings(date_dir / f"{name}.json")
            tiles.append(
                '<a class="tile" href="{name}.html"><span class="name">{name}</span>'
                '<span class="desc">{desc}</span>'
                '<span class="badge chip {sev}">{count} finding(s)</span></a>'.format(
                    name=html.escape(name), desc=html.escape(CHECK_DESCRIPTIONS.get(name, "")),
                    count=count, sev="error" if count else "",
                )
            )
        tab_groups.append(
            f'<h3 class="cat-heading">{html.escape(category)}</h3>\n'
            f'<div class="tabs">\n{chr(10).join(tiles)}\n</div>'
        )

    body = f"""<a class="nav-back" href="../../qc_dashboard.html">&larr; all dates</a>
<h1>QC reports — {date}</h1>
<p class="sub">Click a check to see its findings on its own page.</p>
{chr(10).join(tab_groups)}"""
    (date_dir / "index.html").write_text(
        _page(f"QC reports — {date}", "../../qc_dashboard.html", body)
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
    last_refreshed = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    (reports_dir.parent / "qc_dashboard.html").write_text(
        _page("mia-data-qc reports", "qc_dashboard.html", body, last_refreshed=last_refreshed)
    )
