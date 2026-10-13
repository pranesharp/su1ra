"""build_xlsx / build_docx / build_pdf tools: structured outline -> real file
+ self-contained HTML preview player, mirroring pptx_builder's contract.

Same design as pptx_builder: the model sends JSON, this module owns layout so
it never fights coordinates; the preview is rendered from the same normalized
outline the file writer consumes; unknown-but-recoverable input is normalized
with warnings, only garbage is rejected (OutlineError with a teaching message).

Formats ("school formats"):
  - xlsx: workbook, one or more sheets, rows of cells, styled header row
  - docx: headings/paragraphs/bullet lists/tables (flat block list)
  - pdf:  same block list as docx, rendered with reportlab (pure python)

Previews (artifact pane, sandboxed iframe, NO network — everything inline):
  - xlsx: sheet tabs + grid table
  - docx: paginated A4 pages, theme-matched
  - pdf:  the pages are generated once as HTML; the PDF text is identical
"""

import json
import re
from pathlib import Path

MAX_BLOCKS = 400
MAX_SHEETS = 12
MAX_ROWS = 2000
MAX_CELLS_TEXT = 40_000


class OutlineError(ValueError):
    """Bad outline — the tool result text tells the model how to fix it."""


# --------------------------------------------------------------- normalize

def _s(val, cap=400):
    if val is None:
        return ""
    if not isinstance(val, str):
        val = str(val)
    return val[:cap]


def _cell(val):
    """Spreadsheet/table cell: keep numbers numeric (sorting/formulas), cap text."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    return _s(val, 2000)


def _json_maybe(val, what):
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str) and val.strip()[:1] in "[{":
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            raise OutlineError(
                f"{what}: looks like JSON but does not parse — "
                f"use straight double quotes and no trailing commas: {val[:120]!r}"
            )
    return val


def _stem_of(filename, fallback):
    stem = re.sub(r"\.(xlsx|docx|pdf)$", "", _s(filename, 120), flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", stem).strip("-")
    return stem or fallback


def _unwrap(raw, what):
    """Accept dict; accept a JSON string / {..code..} parked args; unwrap
    alt keys (outline/doc/deck/content)."""
    if isinstance(raw, str):
        raw = _json_maybe(raw, what)
    if not isinstance(raw, dict):
        raise OutlineError(f"{what} must be a JSON object")
    raw = dict(raw)
    for key in ("outline", "doc", "deck", "content", "workbook", "data"):
        if key in raw and not any(k in raw for k in _BODY_KEYS):
            inner = _json_maybe(raw[key], f"'{key}'")
            if isinstance(inner, dict):
                merged = dict(inner)
                merged.update({k: v for k, v in raw.items() if k != key and k in ("filename", "title", "theme") and v})
                raw = merged
            break
    if "code" in raw and not any(k in raw for k in _BODY_KEYS):
        try:
            inner = json.loads(str(raw["code"]))
            if isinstance(inner, dict):
                raw = inner
        except (json.JSONDecodeError, TypeError):
            pass
    return raw


_BODY_KEYS = ("blocks", "sheets", "rows", "paragraphs", "sections")


# ---------------------------------------------------------------- xlsx

def _clean_xlsx(raw, warnings):
    raw = _unwrap(raw, "build_xlsx outline")
    sheets = _json_maybe(raw.get("sheets"), "sheets")
    if isinstance(sheets, dict):
        sheets = [{"name": k, **({"rows": v} if isinstance(v, list) else v)} for k, v in sheets.items()]
    if not isinstance(sheets, list) or not sheets:
        # single sheet straight on the outline
        if isinstance(raw.get("rows"), list):
            sheets = [{"name": raw.get("sheet") or "Sheet1", "rows": raw["rows"]}]
        else:
            raise OutlineError("sheets must be a non-empty array (or put 'rows' directly on the outline)")
    if len(sheets) > MAX_SHEETS:
        raise OutlineError(f"too many sheets ({len(sheets)}) — max {MAX_SHEETS}")

    clean = []
    for i, sh in enumerate(sheets, 1):
        if isinstance(sh, str):
            sh = _json_maybe(sh, f"sheet {i}")
        if not isinstance(sh, dict):
            raise OutlineError(f"sheet {i}: must be an object ({{name, rows}})")
        rows = _json_maybe(sh.get("rows") or sh.get("data"), f"sheet {i} rows")
        if not isinstance(rows, list) or not rows:
            raise OutlineError(f"sheet {i}: 'rows' must be a non-empty array of arrays")
        if len(rows) > MAX_ROWS:
            raise OutlineError(f"sheet {i}: max {MAX_ROWS} rows (got {len(rows)}) — trim or split sheets")
        name = _s(sh.get("name") or (f"Sheet{i}" if len(sheets) > 1 else "Sheet1"), 40).strip() or f"Sheet{i}"
        clean_rows = []
        for r, row in enumerate(rows):
            if isinstance(row, str):
                row = _json_maybe(row, f"sheet {i} row {r}")
            if not isinstance(row, list):
                row = [row]  # lone value per line — be kind
            if len(row) > 40:
                raise OutlineError(f"sheet {i}: max 40 columns (row {r} has {len(row)})")
            clean_rows.append([_cell(c) for c in row])
        clean.append({"name": name[:31], "rows": clean_rows})  # Excel name cap

    title = _s(raw.get("title"), 120)
    return _stem_of(raw.get("filename"), "workbook"), title, clean, warnings


def build_xlsx(arguments: dict, project_dir: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    stem, title, sheets, warnings = _clean_xlsx(arguments or {}, [])
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)
    for sh in sheets:
        ws = wb.create_sheet(sh["name"])
        if title and sh is sheets[0]:
            ws.title = sh["name"]
        for r, row in enumerate(sh["rows"], 1):
            for c, val in enumerate(row, 1):
                cell = ws.cell(row=r, column=c, value=val)
                if r == 1:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="2F6FED")
                    cell.alignment = Alignment(horizontal="left", vertical="center")
        # column widths from content (capped), header freeze
        for c in range(1, (max(len(r) for r in sh["rows"]) if sh["rows"] else 1) + 1):
            width = max((len(str(sh["rows"][r][c - 1])) + 2 for r in range(min(len(sh["rows"]), 60)) if c <= len(sh["rows"][r])), default=10)
            ws.column_dimensions[get_column_letter(c)].width = min(max(width, 9), 60)
        ws.freeze_panes = "A2"
    if title:
        wb.properties.title = title
    path = project_dir / f"{stem}.xlsx"
    wb.save(path)

    preview = project_dir / f"{stem}.preview.html"
    _write_html(preview, "xlsx", stem, {"title": title, "sheets": sheets}, "grid")
    return {"ok": True, "path": path.name, "preview": preview.name,
            "sheets": len(sheets), "warnings": warnings}


# ------------------------------------------------------------ docx / pdf

ALIAS_H1 = ("h1", "heading", "header", "title_slide", "title1")
ALIAS_H2 = ("h2", "subheading", "subtitle", "title2")
ALIAS_P = ("p", "paragraph", "text", "para")
ALIAS_UL = ("bullets", "bullet", "ul", "list", "li")
ALIAS_OL = ("numbers", "numbered", "ol", "ordered")


def _clean_blocks(raw, warnings):
    raw = _unwrap(raw, "document outline")
    blocks = _json_maybe(raw.get("blocks"), "blocks")
    if not isinstance(blocks, list):
        # tolerate paragraphs=[...]/rows=[...] style outlines
        for key in ("paragraphs", "sections", "content_list"):
            if isinstance(raw.get(key), list):
                blocks = raw[key]
                break
    if not isinstance(blocks, list) or not blocks:
        # last resort: a bare string = one paragraph; a {title, text} pair
        if isinstance(raw.get("text"), str) and raw["text"].strip():
            blocks = [{"p": raw["text"]}]
        else:
            raise OutlineError(
                "blocks must be a non-empty array — each block is one of: "
                '{"h1": "..."}, {"h2": "..."}, {"p": "..."}, {"bullets": ["...", ...]}, '
                '{"numbers": [...]}, {"table": {"rows": [["a","b"],...]}} or {"pagebreak": true}'
            )
    if len(blocks) > MAX_BLOCKS:
        raise OutlineError(f"too many blocks ({len(blocks)}) — max {MAX_BLOCKS}")

    clean = []
    for i, b in enumerate(blocks, 1):
        if isinstance(b, str):
            b = {"p": b}
        if isinstance(b, str) or not isinstance(b, dict):
            b = _json_maybe(b, f"block {i}")
        if not isinstance(b, dict):
            raise OutlineError(f"block {i}: must be an object or a string")
        b = dict(b)
        kind = (_s(b.get("kind"), 12) or "").lower()
        if kind in ("pagebreak", "page_break", "break") or ("pagebreak" in b and b["pagebreak"] in (True, None, "")):
            clean.append({"kind": "pagebreak"})
            continue
        # find the payload under any alias
        text = None
        for keys, k in ((ALIAS_H1, "h1"), (ALIAS_H2, "h2"), (ALIAS_P, "p"), (ALIAS_UL, "bullets"), (ALIAS_OL, "numbers")):
            for key in keys:
                if key in b and b[key] not in (None, "", []):
                    text = b[key]
                    found = k
                    break
            if text is not None:
                break
        if "table" in b and b["table"] not in (None, "", []):
            t = _json_maybe(b["table"], f"block {i} table")
            rows = _json_maybe(t.get("rows") or t.get("data"), f"block {i} table rows") if isinstance(t, dict) else t
            if not isinstance(rows, list) or len(rows) < 1:
                raise OutlineError(f"block {i}: table.rows must be a non-empty array of arrays")
            width = None
            clean_rows = []
            for r, row in enumerate(rows):
                if isinstance(row, str):
                    row = _json_maybe(row, f"block {i} table row {r}")
                if not isinstance(row, list):
                    row = [row]
                width = len(row) if width is None else width
                if len(row) != width:
                    raise OutlineError(f"block {i}: all table rows need the same column count (row {r}: {len(row)} vs {width})")
                clean_rows.append([_cell(c) for c in row])
            if len(clean_rows[0]) > 10:
                raise OutlineError(f"block {i}: max 10 table columns")
            clean.append({"kind": "table", "rows": clean_rows, "caption": _s(b.get("caption"), 200)})
            continue
        if text is None:
            warnings.append(f"block {i}: no recognizable content — skipped (got keys: {', '.join(list(b)[:5])})")
            continue
        if found in ("bullets", "numbers"):
            items = _json_maybe(text, f"block {i} {found}")
            if not isinstance(items, list):
                items = [items]
            if len(items) > 100:
                raise OutlineError(f"block {i}: max 100 list items")
            clean.append({"kind": found, "items": [_s(x, 2000) for x in items]})
        else:
            txt = _s(text, 8000)
            if not txt.strip():
                continue
            if found in ("h1", "h2") and not txt.strip():
                warnings.append(f"block {i}: empty {found} skipped")
                continue
            clean.append({"kind": found, "text": txt})

    if not any(b["kind"] != "pagebreak" for b in clean):
        raise OutlineError("outline produced an empty document — add at least one h1/p/bullets/table block")
    title = _s(raw.get("title"), 200) or next((b["text"] for b in clean if b["kind"] == "h1"), "")
    stem = _stem_of(raw.get("filename"), "document")
    return stem, title, clean, warnings


# shared doc style (matches clean-light deck theme)
DOC_STYLE = {
    "font_stack": "'Calibri','Segoe UI',sans-serif",
    "font": "Calibri",
    "fg": "17171C", "muted": "6B6B74", "accent": "2F6FED",
}


def build_docx(arguments: dict, project_dir: Path):
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    stem, title, blocks, warnings = _clean_blocks(arguments or {}, [])
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)


    doc = docx.Document()
    doc = docx.Document()
    st = DOC_STYLE
    st = DOC_STYLE

    def para(text, size, color, bold=False, italic=False, space_after=8, align=None, style=None):
        p = doc.add_paragraph(style=style)
        p.paragraph_format.space_after = Pt(space_after)
        if align:
            p.alignment = align
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = RGBColor.from_string(color)
        run.font.name = st["font"]
        return p

    if title:
        para(title, 24, st["fg"], bold=True, space_after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    for b in blocks:
        if b["kind"] == "h1":
            para(b["text"], 20, st["fg"], bold=True, space_after=6)
        elif b["kind"] == "h2":
            para(b["text"], 15, st["accent"], bold=True, space_after=5)
        elif b["kind"] == "p":
            para(b["text"], 11, st["fg"], space_after=8)
        elif b["kind"] == "bullets":
            for item in b["items"]:
                para(item, 11, st["fg"], style="List Bullet", space_after=3)
        elif b["kind"] == "numbers":
            for item in b["items"]:
                para(item, 11, st["fg"], style="List Number", space_after=3)
        elif b["kind"] == "table":
            rows = b["rows"]
            t = doc.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Light Grid Accent 1"
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    cell = t.cell(r, c)
                    cell.text = val
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.font.bold = True
            if b.get("caption"):
                para(b["caption"], 9, st["muted"], italic=True, space_after=10)
        elif b["kind"] == "pagebreak":
            doc.add_page_break()
    path = project_dir / f"{stem}.docx"
    doc.save(path)

    preview = project_dir / f"{stem}.preview.html"
    _write_html(preview, "docx", stem, {"title": title, "blocks": blocks}, "pages")
    return {"ok": True, "path": path.name, "preview": preview.name,
            "blocks": len(blocks), "warnings": warnings}


def build_pdf(arguments: dict, project_dir: Path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    stem, title, blocks, warnings = _clean_blocks(arguments or {}, [])
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    st = DOC_STYLE
    fg, muted, accent = colors.HexColor("#" + st["fg"]), colors.HexColor("#" + st["muted"]), colors.HexColor("#" + st["accent"])
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=24, textColor=fg, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=accent, spaceAfter=5)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14.5, textColor=fg, spaceAfter=8)
    cap = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=muted, spaceAfter=10)
    tcell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5, leading=12, textColor=fg)
    thead = ParagraphStyle("thead", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=colors.white)

    def esc(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    flow = []
    if title:
        flow.append(Paragraph(esc(title), h1))
        flow.append(Spacer(1, 4))
    for b in blocks:
        if b["kind"] == "h1":
            flow.append(Paragraph(esc(b["text"]), h1))
        elif b["kind"] == "h2":
            flow.append(Paragraph(esc(b["text"]), h2))
        elif b["kind"] == "p":
            flow.append(Paragraph(esc(b["text"]), body))
        elif b["kind"] in ("bullets", "numbers"):
            flow.append(ListFlowable(
                [ListItem(Paragraph(esc(x), body), leftIndent=18) for x in b["items"]],
                bulletType="1" if b["kind"] == "numbers" else "bullet", start=b["kind"] == "numbers" and "1" or None,
            ))
            flow.append(Spacer(1, 6))
        elif b["kind"] == "table":
            rows = b["rows"]
            data = [[Paragraph(esc(c), thead if r == 0 else tcell) for c in row] for r, row in enumerate(rows)]
            tw = (A4[0] - 50 * mm)
            t = Table(data, colWidths=[tw / len(rows[0])] * len(rows[0]))
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), accent),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9C9D2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4FA")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            flow.append(t)
            if b.get("caption"):
                flow.append(Paragraph(esc(b["caption"]), cap))
        elif b["kind"] == "pagebreak":
            flow.append(PageBreak())

    path = project_dir / f"{stem}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=title or stem)
    doc.build(flow)

    preview = project_dir / f"{stem}.preview.html"
    _write_html(preview, "pdf", stem, {"title": title, "blocks": blocks}, "pages")
    return {"ok": True, "path": path.name, "preview": preview.name,
            "blocks": len(blocks), "warnings": warnings}


# ------------------------------------------------------------- html preview

_CSS_PAGES = """<!doctype html><html><head><meta charset="utf-8"><title>%TITLE%</title>
<style>
:root{--fg:#%(fg)s;--muted:#%(muted)s;--accent:#%(accent)s}
html,body{margin:0;background:#3a3a44;font-family:%(font)s}
.page{width:794px;min-height:1050px;background:#fff;color:var(--fg);margin:18px auto;
  padding:64px 72px;box-sizing:border-box;box-shadow:0 2px 14px rgba(0,0,0,.35);position:relative}
h1.doctitle{font-size:30px;margin:0 0 4px;text-align:center}
.doctitle-rule{width:64px;height:3px;background:var(--accent);margin:0 auto 26px}
h1{font-size:21px;margin:22px 0 8px}
h2{font-size:16px;color:var(--accent);margin:18px 0 6px}
p{font-size:12.5px;line-height:1.55;margin:0 0 10px}
ul,ol{font-size:12.5px;line-height:1.55;margin:0 0 10px;padding-left:22px}
li{margin-bottom:4px}
table{border-collapse:collapse;width:100%%;margin:8px 0 4px;font-size:11.5px}
th{background:var(--accent);color:#fff;text-align:left;padding:6px 9px;font-weight:700}
td{border:1px solid #c9c9d2;padding:5px 9px}
tbody tr:nth-child(odd) td{background:#f2f4fa}
.caption{font-size:10px;color:var(--muted);font-style:italic;margin:2px 0 12px}
.break{border-top:1px dashed #b9b9c4;margin:26px 0;padding-top:4px;color:var(--muted);font-size:10px}
</style></head><body>%BODY%</body></html>"""

_CSS_GRID = """<!doctype html><html><head><meta charset="utf-8"><title>%TITLE%</title>
<style>
:root{--fg:#%(fg)s;--muted:#%(muted)s;--accent:#%(accent)s}
html,body{margin:0;background:#23232b;font-family:%(font)s;color:var(--fg)}
#tabs{position:sticky;top:0;display:flex;gap:4px;padding:8px 10px;background:#1b1b23;border-bottom:1px solid #34343e}
#tabs button{background:none;border:1px solid #43434f;color:var(--fg);font:inherit;font-size:12px;
  padding:3px 14px;cursor:pointer}
#tabs button.on{border-color:var(--accent);color:var(--accent);font-weight:700}
.sheetwrap{padding:12px}
.sheet{display:none;overflow:auto;max-height:calc(100vh - 52px)}
.sheet.on{display:block}
table{border-collapse:collapse;font-size:12.5px;background:#fff;color:#17171c}
td,th{border:1px solid #c9c9d2;padding:4px 10px;min-width:64px;max-width:420px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
tr:first-child *{background:#2f6fed;color:#fff;font-weight:700}
tbody tr:nth-child(odd) td{background:#f6f7fb}
th{position:sticky;top:0}
</style></head><body>
<div id="tabs"></div>
<div class="sheetwrap">%BODY%</div>
<script>
const tabs = document.querySelectorAll('.sheet');
const bar = document.getElementById('tabs');
tabs.forEach((s, i) => {
  const b = document.createElement('button');
  b.textContent = s.dataset.name;
  b.onclick = () => { tabs.forEach(x => x.classList.remove('on'));
    bar.querySelectorAll('button').forEach(x => x.classList.remove('on'));
    s.classList.add('on'); b.classList.add('on'); };
  bar.appendChild(b);
  if (i === 0) { s.classList.add('on'); b.classList.add('on'); }
});
</script></body></html>"""


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _docx_body(data):
    out = []
    if data.get("title"):
        out.append(f'<h1 class="doctitle">{_esc(data["title"])}</h1><div class="doctitle-rule"></div>')
    for b in data["blocks"]:
        if b["kind"] == "h1":
            out.append(f"<h1>{_esc(b['text'])}</h1>")
        elif b["kind"] == "h2":
            out.append(f"<h2>{_esc(b['text'])}</h2>")
        elif b["kind"] == "p":
            out.append(f"<p>{_esc(b['text'])}</p>")
        elif b["kind"] == "bullets":
            out.append("<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in b["items"]) + "</ul>")
        elif b["kind"] == "numbers":
            out.append("<ol>" + "".join(f"<li>{_esc(x)}</li>" for x in b["items"]) + "</ol>")
        elif b["kind"] == "table":
            head = "".join(f"<th>{_esc(c)}</th>" for c in b["rows"][0])
            body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in b["rows"][1:])
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            if b.get("caption"):
                out.append(f'<div class="caption">{_esc(b["caption"])}</div>')
        elif b["kind"] == "pagebreak":
            out.append('<div class="break">— page break —</div>')
    return "".join(out)


def _xlsx_body(data):
    out = []
    for i, sh in enumerate(data["sheets"]):
        rows = sh["rows"]
        head = "".join(f"<th>{_esc(c)}</th>" for c in rows[0])
        body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
        out.append(
            f'<section class="sheet" data-name="{_esc(sh["name"])}">'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>'
        )
    return "".join(out)


def _write_html(path, fmt, stem, data, style):
    tpl = _CSS_GRID if style == "grid" else _CSS_PAGES
    title = data.get("title") or stem
    body = _xlsx_body(data) if fmt == "xlsx" else _docx_body(data)
    html = (
        tpl.replace("%TITLE%", _esc(title))
        .replace("%fg%", DOC_STYLE["fg"]).replace("%muted%", DOC_STYLE["muted"])
        .replace("%accent%", DOC_STYLE["accent"]).replace("%font%", DOC_STYLE["font_stack"])
        .replace("%BODY%", body)
    )
    Path(path).write_text(html, encoding="utf-8")


# ------------------------------------------------- previews of EXISTING files
# For files that were NOT made by the build_* tools (model used run_python, or
# the user dropped a file into the project): read the real file and render the
# same style of <name>.preview.html next to it. Read-only best effort.

def preview_existing(path: Path):
    """Generate <name>.preview.html for an existing pptx/xlsx/docx/pdf/svg."""
    path = Path(path)
    ext = path.suffix.lower()

    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(str(path))
        slides = []
        for sl in prs.slides:
            texts = []
            for sh in sl.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip():
                    texts.append(sh.text_frame.text.strip())
            slides.append(texts)
        # normalized blocks (kind/text/items) — same shape _docx_body consumes
        blocks = []
        for i, texts in enumerate(slides, 1):
            if not texts:
                texts = [f"[slide {i}]"]
            blocks.append({"kind": "h2", "text": f"Slide {i}: {texts[0]}"})
            items = [ln.strip() for t in texts[1:] for ln in t.splitlines() if ln.strip()]
            if items:
                blocks.append({"kind": "bullets", "items": items[:60]})
        data = {"title": path.stem, "blocks": blocks}
        out = path.with_suffix(".preview.html")
        _write_html(out, "docx", path.stem, data, "pages")
        return {"ok": True, "path": out.name, "source": path.name}

    if ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True, data_only=True)
        sheets = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(max_row=MAX_ROWS, values_only=True):
                rows.append(["" if v is None else str(v) for v in row])
            sheets.append({"name": ws.title, "rows": rows or [["(empty)"]]})
        wb.close()
        out = path.with_suffix(".preview.html")
        _write_html(out, "xlsx", path.stem, {"title": path.stem, "sheets": sheets}, "grid")
        return {"ok": True, "path": out.name, "source": path.name}

    if ext == ".docx":
        import docx as docxlib
        d = docxlib.Document(str(path))
        blocks = []
        for p in d.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name or "").lower()
            if "heading 1" in style or "title" in style:
                blocks.append({"kind": "h1", "text": txt})
            elif "heading 2" in style:
                blocks.append({"kind": "h2", "text": txt})
            elif "list bullet" in style:
                blocks.append({"kind": "bullets", "items": [txt]})
            elif "list number" in style:
                blocks.append({"kind": "numbers", "items": [txt]})
            else:
                blocks.append({"kind": "p", "text": txt})
        for t in d.tables:
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            if rows:
                blocks.append({"kind": "table", "rows": rows})
        out = path.with_suffix(".preview.html")
        _write_html(out, "docx", path.stem, {"title": path.stem, "blocks": blocks}, "pages")
        return {"ok": True, "path": out.name, "source": path.name}

    if ext == ".pdf":
        from pypdf import PdfReader
        rd = PdfReader(str(path))
        blocks = []
        for i, page in enumerate(rd.pages, 1):
            if i > 60:
                blocks.append({"p": f"... ({len(rd.pages)} pages total — showing first 60)"})
                break
            txt = (page.extract_text() or "").strip()
            if txt:
                blocks.append({"kind": "h2", "text": f"Page {i}"})
                blocks.append({"kind": "p", "text": txt[:4000]})
        out = path.with_suffix(".preview.html")
        _write_html(out, "docx", path.stem, {"title": path.stem, "blocks": blocks}, "pages")
        return {"ok": True, "path": out.name, "source": path.name}

    if ext == ".svg":
        svg = path.read_text(encoding="utf-8", errors="replace")
        if "<svg" not in svg[:2000].lower():
            raise OutlineError("not an SVG file")
        # same checkerboard wrapper as the in-chat svg preview
        doc = (
            '<!doctype html><html><head><meta charset="utf-8"><style>'
            "html,body{margin:0;height:100%}"
            "body{display:flex;align-items:center;justify-content:center;"
            "background:linear-gradient(45deg,#191922 25%,transparent 25%,transparent 75%,#191922 75%) 0 0/16px 16px,"
            "linear-gradient(45deg,#191922 25%,transparent 25%,transparent 75%,#191922 75%) 8px 8px/16px 16px,#101018}"
            "svg{max-width:min(100%,420px);max-height:280px;width:auto;height:auto}"
            "</style></head><body>" + svg + "</body></html>"
        )
        out = path.with_suffix(".preview.html")
        out.write_text(doc, encoding="utf-8")
        return {"ok": True, "path": out.name, "source": path.name}

    raise OutlineError(f"no preview support for '{ext}' — pptx/xlsx/docx/pdf/svg only")
