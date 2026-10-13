"""build_pptx tool: structured outline -> real .pptx + self-contained HTML deck player.

Design (why two renderers):
  The model never touches pptx coordinates — it sends a JSON outline, and this
  module owns layout. The .pptx and the preview .html are both rendered from
  the SAME outline + THEME + LAYOUT constants, so they cannot drift apart.
  Preview px map 1:1 to slide points (960x540 stage = 13.333x7.5in at 72px/in),
  so font sizes and margins match the deck by construction.

The player is fully inline (no CDN): the artifact iframe is sandboxed with no
network, and local-first means no external fetches, ever.
"""

import json
import re
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5

# In inches — the single source of truth for geometry. The HTML player receives
# these pre-converted to px (in * 72), so both renderers share one dict.
LAYOUT_IN = {
    "mx": 0.9,          # side margin
    "rule_y": 2.45,     # title-slide accent rule
    "kicker_y": 2.62,
    "title_y": 2.95,
    "subtitle_y": 4.55,
    "head_y": 0.62,     # content-slide title
    "body_y": 1.95,
    "num_y": 7.02,      # slide number baseline
}
LAYOUT_PX = {k: round(v * 72) for k, v in LAYOUT_IN.items()}

THEMES = {
    "terminal-dark": {
        "bg": "0B0B0F", "panel": "14141C", "fg": "E8E8F0", "muted": "8B8B98",
        "accent": "7BE8A8", "on_accent": "0B0B0F",
        "font": "Consolas", "font_stack": "'Consolas','DejaVu Sans Mono',monospace",
    },
    "clean-light": {
        "bg": "F7F7F4", "panel": "FFFFFF", "fg": "17171C", "muted": "6B6B74",
        "accent": "2F6FED", "on_accent": "FFFFFF",
        "font": "Calibri", "font_stack": "'Calibri','Segoe UI',sans-serif",
    },
}
DEFAULT_THEME = "terminal-dark"

VALID_LAYOUTS = ("title", "section", "bullets", "two_col", "table", "image")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"}

# Models rarely fail the same way twice, so normalize instead of rejecting.
LAYOUT_ALIASES = {
    "title_slide": "title", "cover": "title", "heading_slide": "title",
    "heading": "section", "divider": "section", "section_break": "section", "chapter": "section",
    "bullet": "bullets", "list": "bullets", "points": "bullets", "content": "bullets", "text": "bullets",
    "columns": "two_col", "two_columns": "two_col", "two-column": "two_col", "comparison": "two_col", "split": "two_col",
    "picture": "image", "photo": "image",
}
THEME_ALIASES = {"dark": "terminal-dark", "terminal": "terminal-dark", "mono": "terminal-dark", "light": "clean-light", "bright": "clean-light"}
BULLET_KEYS = ("bullets", "points", "bullet_points", "items")
ROW_KEYS = ("rows", "table", "data")


def _json_maybe(val, what):
    """Accept list/dict as-is; accept a JSON-encoded string and parse it."""
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


def _first_list(d, keys, what):
    for k in keys:
        if k in d:
            return _json_maybe(d[k], what), k
    return None, None


def _infer_layout(s):
    """Decide the layout from whichever keys are present (layout key missing/unknown)."""
    if any(k in s for k in ROW_KEYS):
        return "table"
    if "left" in s or "right" in s:
        return "two_col"
    if any(k in s for k in BULLET_KEYS):
        return "bullets"
    if "image" in s or "picture" in s:
        return "image"
    if "subtitle" in s:
        return "title"
    if s.get("title"):
        return "section"
    raise OutlineError(f"slide has no recognizable content keys — need one of: title, bullets, rows, left/right, image (got: {', '.join(list(s)[:6]) or 'empty'})")

MAX_SLIDES = 60
MAX_TEXT = 200_000


class OutlineError(ValueError):
    """Bad outline — the tool result text tells the model how to fix it."""


# ---------------------------------------------------------------- validation

def _s(val, what, cap):
    if val is None:
        return ""
    if not isinstance(val, str):
        val = str(val)
    if len(val) > cap:
        raise OutlineError(f"{what}: over {cap} chars — shorten it")
    return val


def _clean_outline(raw):
    # Models wrap things: whole outline as a string, one slide object instead
    # of a list, the outline under a different key. Unwrap before validating.
    if isinstance(raw, str):
        raw = _json_maybe(raw, "outline")
    if not isinstance(raw, dict):
        raise OutlineError("outline must be a JSON object")
    for key in ("outline", "deck", "slide_deck", "presentation"):
        if "slides" not in raw and key in raw:
            inner = _json_maybe(raw[key], f"'{key}'")
            if isinstance(inner, dict) and "slides" in inner:
                merged = dict(inner)  # the alt key held a whole outline
                merged.setdefault("filename", raw.get("filename") or "")
                merged.setdefault("theme", raw.get("theme") or "")
                raw = merged
            else:
                raw = dict(raw)
                raw["slides"] = inner
            break
    if "slides" not in raw and isinstance(raw.get("code"), str) and raw["code"].strip()[:1] in "[{":
        # finalize_tool_call parks unparseable-JSON args under "code" — the
        # outline may still be recoverable from that string.
        inner = _json_maybe(raw["code"], "outline")
        if isinstance(inner, dict):
            raw = inner
        elif isinstance(inner, list):
            raw = {"slides": inner}

    filename = _s(raw.get("filename"), "filename", 120).strip()
    theme_name = (_s(raw.get("theme"), "theme", 40) or DEFAULT_THEME).strip().lower()
    theme_name = THEME_ALIASES.get(theme_name, theme_name)
    if theme_name not in THEMES:
        warnings0 = [f"theme '{theme_name}' is not one of {', '.join(THEMES)} — using {DEFAULT_THEME}"]
        theme_name = DEFAULT_THEME
    else:
        warnings0 = []

    slides = _json_maybe(raw.get("slides"), "slides")
    if isinstance(slides, dict):
        slides = [slides]
    if not isinstance(slides, list) or not slides:
        raise OutlineError("slides must be a non-empty array (a single slide object also works)")
    if len(slides) > MAX_SLIDES:
        raise OutlineError(f"too many slides ({len(slides)}) — max {MAX_SLIDES}")

    clean, warnings = [], list(warnings0)
    for i, s in enumerate(slides, 1):
        if isinstance(s, str):
            s = _json_maybe(s, f"slide {i}")
        if not isinstance(s, dict):
            raise OutlineError(f"slide {i}: must be an object")
        s = dict(s)
        layout = (_s(s.get("layout"), f"slide {i} layout", 30) or "").strip().lower()
        layout = LAYOUT_ALIASES.get(layout, layout)
        if layout not in VALID_LAYOUTS:
            inferred = _infer_layout(s)
            warnings.append(f"slide {i}: unknown layout '{layout}' — inferred '{inferred}' from its keys")
            layout = inferred

        # bullets/rows/columns may arrive under alias keys or as JSON strings.
        bl, bl_key = _first_list(s, BULLET_KEYS, f"slide {i} bullets")
        rl, rl_key = _first_list(s, ROW_KEYS, f"slide {i} table rows")
        if layout == "bullets":
            if not isinstance(bl, list) or not bl:
                raise OutlineError(
                    f"slide {i} (bullets): '{bl_key or 'bullets'}' must be a non-empty array of strings "
                    "(a JSON-encoded array string also works)"
                )
            if len(bl) > 14:
                raise OutlineError(f"slide {i}: max 14 bullets (got {len(bl)}) — split across slides")
            s["bullets"] = [_s(b, f"slide {i} bullet {j}", 400) for j, b in enumerate(bl, 1)]

        out = {
            "layout": layout,
            "title": _s(s.get("title"), f"slide {i} title", 220),
            "notes": _s(s.get("notes"), f"slide {i} notes", 2000),
        }
        if layout in ("title", "section") and not out["title"]:
            # a lone title-ish slide: take the first bullet/heading-ish value
            for k in ("heading", "name", "bullets", "points", "text"):
                v = s.get(k)
                if isinstance(v, str) and v.strip():
                    out["title"] = v.strip()[:220]
                    break
                if isinstance(v, list) and v and isinstance(v[0], str):
                    out["title"] = v[0].strip()[:220]
                    break
            if not out["title"]:
                raise OutlineError(f"slide {i} ({layout}): title is required")
        if layout == "title":
            out["subtitle"] = _s(s.get("subtitle"), f"slide {i} subtitle", 300)
        if layout == "bullets":
            out["bullets"] = s["bullets"]
        if layout == "two_col":
            for side, aliases in (("left", ("left_bullets", "col1", "column1", "first")), ("right", ("right_bullets", "col2", "column2", "second"))):
                val, key = _first_list(s, (side,) + aliases, f"slide {i} {side}")
                if not isinstance(val, list) or not val:
                    raise OutlineError(f"slide {i} (two_col): '{key or side}' must be a non-empty array")
                if len(val) > 14:
                    raise OutlineError(f"slide {i}: max 14 items per column")
                out[side] = [_s(b, f"slide {i} {side} {j}", 400) for j, b in enumerate(val, 1)]
            out["left_title"] = _s(s.get("left_title"), f"slide {i} left_title", 120)
            out["right_title"] = _s(s.get("right_title"), f"slide {i} right_title", 120)
        if layout == "table":
            rows = rl
            if not isinstance(rows, list) or len(rows) < 2:
                raise OutlineError(
                    f"slide {i} (table): '{rl_key or 'rows'}' must be an array with a header row + at least one data row"
                )
            if len(rows) > 24:
                raise OutlineError(f"slide {i}: max 24 table rows — trim or split")
            width = None
            clean_rows = []
            for r, row in enumerate(rows):
                if isinstance(row, str):
                    row = _json_maybe(row, f"slide {i} table row {r}")
                if not isinstance(row, list) or not row:
                    raise OutlineError(f"slide {i}: table row {r} must be a non-empty array")
                width = len(row) if width is None else width
                if len(row) != width:
                    raise OutlineError(f"slide {i}: all table rows must have the same number of columns (row {r} has {len(row)}, expected {width})")
                if width > 8:
                    raise OutlineError(f"slide {i}: max 8 table columns (got {width})")
                clean_rows.append([_s(c, f"slide {i} cell {r},{c0}", 300) for c0, c in enumerate(row)])
            out["rows"] = clean_rows
        if layout == "image":
            out["image"] = _s(s.get("image") or s.get("picture") or s.get("image_path"), f"slide {i} image", 400).strip()
            if not out["image"]:
                raise OutlineError(f"slide {i} (image): 'image' path is required (relative to the project folder)")
            out["caption"] = _s(s.get("caption"), f"slide {i} caption", 300)
        total = len(out.get("title", "")) + len(out.get("notes", "")) + sum(len(x) for x in (out.get("bullets") or []))
        if total > MAX_TEXT // MAX_SLIDES:
            raise OutlineError(f"slide {i}: too much text")
        clean.append(out)

    if not filename:
        # No filename? Derive a sane one from the first title.
        seed = clean[0]["title"] or "deck"
        filename = seed[:60]
    stem = re.sub(r"\.pptx$", "", filename, flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", stem).strip("-") or "deck"
    return stem, theme_name, clean, warnings


# ---------------------------------------------------------------- pptx render

def _rgb(hex6):
    return RGBColor.from_string(hex6)


def _box(slide, x_in, y_in, w_in, h_in, theme=None):
    """Textbox with plain styling helpers attached."""
    box = slide.shapes.add_textbox(Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    tf = box.text_frame
    tf.word_wrap = True
    return tf


def _para(tf, first, text, size, color, bold=False, italic=False, align=PP_ALIGN.LEFT, space_after=None, spacing=None):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    if space_after is not None:
        p.space_after = Pt(space_after)
    if spacing is not None:
        p.line_spacing = spacing
    run = p.add_run()
    run.text = text
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = _rgb(color)
    return p


def _accent_rule(slide, x_in, y_in, w_in, theme, h_in=0.055):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(theme["accent"])
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _slide_no(slide, idx, total, theme):
    tf = _box(slide, SLIDE_W_IN - LAYOUT_IN["mx"] - 1.2, LAYOUT_IN["num_y"], 1.2, 0.32)
    _para(tf, True, f"{idx} / {total}", 10, theme["muted"], align=PP_ALIGN.RIGHT)


def _set_notes(slide, notes):
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def _fill_bullets(tf, items, theme, size=20, gap=12):
    first = True
    for item in items:
        if item.startswith("> "):  # "> text" = emphasis line in the accent color
            _para(tf, first, item[2:].strip(), size, theme["accent"], bold=True, space_after=gap, spacing=1.12)
        else:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            p.space_after = Pt(gap)
            p.line_spacing = 1.12
            dash = p.add_run()
            dash.text = "— "
            dash.font.size = Pt(size)
            dash.font.color.rgb = _rgb(theme["accent"])
            run = p.add_run()
            run.text = item
            run.font.size = Pt(size)
            run.font.color.rgb = _rgb(theme["fg"])
        first = False


def _fit_picture(slide, img_path, x_in, y_in, w_in, h_in):
    """Center an image inside a box, preserving aspect ratio."""
    from PIL import Image
    with Image.open(img_path) as im:
        iw, ih = im.size
    scale = min(w_in / (iw / 96), h_in / (ih / 96))
    pw, ph = (iw / 96) * scale, (ih / 96) * scale
    slide.shapes.add_picture(
        str(img_path), Inches(x_in + (w_in - pw) / 2), Inches(y_in + (h_in - ph) / 2),
        width=Inches(pw), height=Inches(ph),
    )


def _render_pptx(path, theme_name, slides, project_dir, warnings):
    theme = THEMES[theme_name]
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    blank = prs.slide_layouts[6]
    mx = LAYOUT_IN["mx"]
    cw = SLIDE_W_IN - 2 * mx
    total = len(slides)

    for idx, s in enumerate(slides, 1):
        slide = prs.slides.add_slide(blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = _rgb(theme["bg"])

        if s["layout"] == "title":
            _accent_rule(slide, mx, LAYOUT_IN["rule_y"], 1.1, theme, h_in=0.06)
            tf = _box(slide, mx, LAYOUT_IN["kicker_y"], cw, 0.4)
            _para(tf, True, (s.get("subtitle") or "presentation").upper(), 13, theme["accent"], bold=True)
            tf = _box(slide, mx, LAYOUT_IN["title_y"], cw, 1.55)
            tf.vertical_anchor = MSO_ANCHOR.TOP
            _para(tf, True, s["title"], 44, theme["fg"], bold=True, spacing=1.02)
        elif s["layout"] == "section":
            _accent_rule(slide, mx, LAYOUT_IN["rule_y"], 1.1, theme, h_in=0.06)
            tf = _box(slide, mx, LAYOUT_IN["kicker_y"], cw, 0.4)
            _para(tf, True, f"{idx:02d}", 14, theme["muted"], bold=True)
            tf = _box(slide, mx, LAYOUT_IN["title_y"], cw, 1.7)
            _para(tf, True, s["title"], 46, theme["fg"], bold=True, spacing=1.02)
        else:
            tf = _box(slide, mx, LAYOUT_IN["head_y"], cw, 1.0)
            _para(tf, True, s["title"] or " ", 30, theme["fg"], bold=True)
            _accent_rule(slide, mx, LAYOUT_IN["head_y"] + 1.02, 0.55, theme, h_in=0.045)
            body_y, body_h = LAYOUT_IN["body_y"], SLIDE_H_IN - LAYOUT_IN["body_y"] - 0.55

            if s["layout"] == "bullets":
                tf = _box(slide, mx, body_y, cw, body_h)
                _fill_bullets(tf, s["bullets"], theme)
            elif s["layout"] == "two_col":
                half = (cw - 0.6) / 2
                for side, x in (("left", mx), ("right", mx + half + 0.6)):
                    if s.get(f"{side}_title"):
                        tf = _box(slide, x, body_y, half, 0.45)
                        _para(tf, True, s[f"{side}_title"], 17, theme["accent"], bold=True)
                        tf = _box(slide, x, body_y + 0.5, half, body_h - 0.5)
                    else:
                        tf = _box(slide, x, body_y, half, body_h)
                    _fill_bullets(tf, s[side], theme, size=18, gap=10)
            elif s["layout"] == "table":
                rows = s["rows"]
                cols = len(rows[0])
                gf = slide.shapes.add_table(len(rows), cols, Inches(mx), Inches(body_y), Inches(cw), Inches(min(body_h, 0.42 * len(rows))))
                table = gf.table
                col_w = Inches(cw / cols)
                for c in range(cols):
                    table.columns[c].width = col_w
                for r, row in enumerate(rows):
                    table.rows[r].height = Inches(0.42)
                    for c, val in enumerate(row):
                        cell = table.cell(r, c)
                        cell.margin_left = cell.margin_right = Inches(0.1)
                        cell.margin_top = cell.margin_bottom = Inches(0.05)
                        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = _rgb(theme["accent"] if r == 0 else (theme["panel"] if r % 2 else theme["bg"]))
                        f = cell.text_frame.paragraphs[0].add_run()
                        f.text = val
                        f.font.size = Pt(14 if r == 0 else 13)
                        f.font.bold = r == 0
                        f.font.color.rgb = _rgb(theme["on_accent"] if r == 0 else theme["fg"])
            elif s["layout"] == "image":
                cap_h = 0.45 if s.get("caption") else 0.0
                img = project_dir / s["image"]
                if img.is_file() and img.suffix.lower() in IMAGE_EXTS:
                    try:
                        _fit_picture(slide, img, mx, body_y, cw, body_h - cap_h)
                    except Exception as exc:
                        warnings.append(f"slide {idx}: image '{s['image']}' could not be embedded ({exc})")
                        tf = _box(slide, mx, body_y, cw, body_h - cap_h)
                        _para(tf, True, f"[ image: {s['image']} ]", 16, theme["muted"])
                else:
                    if img.exists():
                        warnings.append(f"slide {idx}: '{s['image']}' is not a supported image ({', '.join(sorted(IMAGE_EXTS))})")
                    else:
                        warnings.append(f"slide {idx}: image '{s['image']}' not found in the project — placeholder used")
                    tf = _box(slide, mx, body_y, cw, body_h - cap_h)
                    _para(tf, True, f"[ image: {s['image']} ]", 16, theme["muted"])
                if s.get("caption"):
                    tf = _box(slide, mx, SLIDE_H_IN - 0.55 - cap_h + 0.1, cw, cap_h)
                    _para(tf, True, s["caption"], 12, theme["muted"], italic=True)

        if s["layout"] != "title":
            _slide_no(slide, idx, total, theme)
        _set_notes(slide, s["notes"])

    prs.save(str(path))


# --------------------------------------------------------------- html player

_PLAYER_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>deck preview</title>
<style>
  :root { --bg:#%BG%; --panel:#%PANEL%; --fg:#%FG%; --muted:#%MUTED%; --accent:#%ACCENT%; }
  html, body { margin:0; height:100%%; background:var(--bg); overflow:hidden;
    font-family:%FONT%; }
  #wrap { position:fixed; inset:0 0 44px 0; display:flex; align-items:center; justify-content:center; }
  #stage { position:relative; width:960px; height:540px; background:var(--bg);
    transform-origin:center center; overflow:hidden; box-shadow:0 0 0 1px rgba(128,128,140,.25); }
  .slide { position:absolute; inset:0; display:none; }
  .slide.on { display:block; }
  .rule { position:absolute; left:%mx%px; width:79px; height:4px; background:var(--accent); }
  .abs { position:absolute; left:%mx%px; width:830px; margin:0; }
  .kicker { color:var(--accent); font-weight:700; letter-spacing:.14em; }
  .h-title { color:var(--fg); font-weight:700; line-height:1.05; }
  .sub { color:var(--muted); }
  .num { position:absolute; right:65px; color:var(--muted); font-size:10px; }
  ul.b { list-style:none; margin:0; padding:0; color:var(--fg); }
  ul.b li { padding-left:26px; text-indent:-26px; margin-bottom:12px; line-height:1.12; }
  ul.b li::before { content:"— "; color:var(--accent); }
  ul.b li.em { color:var(--accent); font-weight:700; padding-left:0; text-indent:0; }
  ul.b li.em::before { content:""; }
  .cols { position:absolute; top:%body%px; left:%mx%px; width:830px; display:flex; gap:43px; }
  .col { flex:1; }
  .col h3 { margin:0 0 10px; color:var(--accent); font-size:17px; }
  table.t { position:absolute; top:%body%px; left:%mx%px; border-collapse:collapse; width:830px; }
  table.t td, table.t th { border:1px solid rgba(128,128,140,.3); padding:7px 10px; font-size:13px;
    text-align:left; color:var(--fg); overflow:hidden; }
  table.t th { background:var(--accent); color:#%ON_ACCENT%; font-weight:700; }
  table.t tr:nth-child(odd) td { background:var(--panel); }
  .imgbox { position:absolute; top:%body%px; left:%mx%px; width:830px; height:%imgh%px;
    display:flex; align-items:center; justify-content:center; }
  .imgbox img { max-width:100%%; max-height:100%%; }
  .imgbox .ph { color:var(--muted); font-size:16px; }
  .caption { position:absolute; bottom:14px; left:%mx%px; width:830px; color:var(--muted);
    font-size:12px; font-style:italic; }
  #bar { position:fixed; left:0; right:0; bottom:0; height:44px; display:flex; align-items:center;
    justify-content:center; gap:14px; color:var(--muted); font-size:12px; user-select:none; }
  #bar b { color:var(--fg); font-weight:400; }
  button { background:none; border:1px solid rgba(128,128,140,.4); color:var(--fg); font:inherit;
    font-size:12px; padding:3px 12px; cursor:pointer; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  #prog { position:fixed; left:0; bottom:44px; height:2px; background:var(--accent); width:0; }
</style>
</head>
<body>
<div id="wrap"><div id="stage"></div></div>
<div id="prog"></div>
<div id="bar">
  <button id="prev">◀ prev</button>
  <span><b id="cur">1</b> / <span id="tot">1</span></span>
  <button id="next">next ▶</button>
  <span style="opacity:.6">← → space · click sides</span>
</div>
<script>
const DECK = %DECK%;
const stage = document.getElementById('stage');
const L = DECK.layout;

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function bullets(items) {
  return '<ul class="b">' + items.map(b => b.startsWith('> ')
    ? '<li class="em">' + esc(b.slice(2).trim()) + '</li>'
    : '<li>' + esc(b) + '</li>').join('') + '</ul>';
}

DECK.slides.forEach((s, i) => {
  const n = (i + 1) + ' / ' + DECK.slides.length;
  const num = '<div class="num" style="bottom:' + (540 - L.num_y - 8) + 'px">' + n + '</div>';
  let html = '';
  if (s.layout === 'title' || s.layout === 'section') {
    html = '<div class="rule" style="top:' + L.rule_y + 'px"></div>'
      + '<h4 class="abs kicker" style="top:' + L.kicker_y + 'px;font-size:13px">'
      + esc(s.layout === 'title' ? (s.subtitle || 'presentation').toUpperCase() : String(i + 1).padStart(2, '0')) + '</h4>'
      + '<h1 class="abs h-title" style="top:' + L.title_y + 'px;font-size:'
      + (s.layout === 'title' ? 44 : 46) + 'px">' + esc(s.title) + '</h1>' + num;
  } else {
    html = '<h2 class="abs h-title" style="top:' + L.head_y + 'px;font-size:30px">' + esc(s.title) + '</h2>'
      + '<div class="rule" style="top:' + (L.head_y + 74) + 'px;width:40px"></div>';
    if (s.layout === 'bullets') {
      html += '<div class="abs" style="top:' + L.body_y + 'px;font-size:20px">' + bullets(s.bullets) + '</div>';
    } else if (s.layout === 'two_col') {
      const col = (side, t) => '<div class="col">'
        + (t ? '<h3>' + esc(t) + '</h3>' : '')
        + '<div style="font-size:18px">' + bullets(s[side]) + '</div></div>';
      html += '<div class="cols">' + col('left', s.left_title) + col('right', s.right_title) + '</div>';
    } else if (s.layout === 'table') {
      const head = s.rows[0].map(c => '<th>' + esc(c) + '</th>').join('');
      const body = s.rows.slice(1).map(r => '<tr>' + r.map(c => '<td>' + esc(c) + '</td>').join('') + '</tr>').join('');
      html += '<table class="t"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>';
    } else if (s.layout === 'image') {
      html += '<div class="imgbox">'
        + (s.dataurl ? '<img src="' + s.dataurl + '" alt="">'
                     : '<span class="ph">[ image: ' + esc(s.image) + ' ]</span>')
        + '</div>'
        + (s.caption ? '<div class="caption">' + esc(s.caption) + '</div>' : '');
    }
    html += num;
  }
  const el = document.createElement('div');
  el.className = 'slide';
  el.innerHTML = html;
  stage.appendChild(el);
});

let cur = 0;
const slides = document.querySelectorAll('.slide');
function show(i) {
  cur = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach((el, j) => el.classList.toggle('on', j === cur));
  document.getElementById('cur').textContent = cur + 1;
  document.getElementById('prog').style.width = (100 * (cur + 1) / slides.length) + '%';
}
function fit() {
  const wrap = document.getElementById('wrap');
  const s = Math.min(wrap.clientWidth / 960, wrap.clientHeight / 540) * 0.97;
  stage.style.transform = 'scale(' + s + ')';
}
document.getElementById('tot').textContent = slides.length;
document.getElementById('prev').onclick = () => show(cur - 1);
document.getElementById('next').onclick = () => show(cur + 1);
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') show(cur + 1);
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') show(cur - 1);
  else if (e.key === 'Home') show(0);
  else if (e.key === 'End') show(slides.length - 1);
});
document.addEventListener('click', (e) => {
  if (e.target.closest('#bar')) return;
  const r = stage.getBoundingClientRect();
  if (e.clientX < r.left + r.width * 0.3) show(cur - 1);
  else if (e.clientX < r.right) show(cur + 1);
});
addEventListener('resize', fit);
fit(); show(0);
</script>
</body>
</html>
"""


def _b64_dataurls(clean_slides, project_dir, warnings):
    """Embed images as data URLs so the sandboxed preview iframe can show them
    (it has no file:// access). Reuses the same existence checks as the pptx render."""
    import base64
    out = {}
    for idx, s in enumerate(clean_slides, 1):
        if s["layout"] != "image":
            continue
        img = project_dir / s["image"]
        if img.is_file() and img.suffix.lower() in IMAGE_EXTS:
            try:
                mime = "image/jpeg" if img.suffix.lower() in (".jpg", ".jpeg") else f"image/{img.suffix.lower().lstrip('.')}"
                out[idx] = f"data:{mime};base64," + base64.b64encode(img.read_bytes()).decode()
            except Exception as exc:
                warnings.append(f"slide {idx}: preview could not embed '{s['image']}' ({exc})")
    return out


def _render_player(path, theme_name, clean_slides, warnings):
    theme = THEMES[theme_name]
    dataurls = _b64_dataurls(clean_slides, Path(path).parent, warnings)
    slides_out = []
    for idx, s in enumerate(clean_slides, 1):
        s = dict(s)
        if s["layout"] == "image":
            s["dataurl"] = dataurls.get(idx)
        slides_out.append(s)
    deck = json.dumps({
        "theme": {k: ("#" + v if k in ("bg", "panel", "fg", "muted", "accent", "on_accent") else v) for k, v in theme.items()},
        "layout": LAYOUT_PX,
        "slides": slides_out,
    }).replace("</", "<\\/")  # keep </script> inside JSON from terminating the tag

    imgh = round((SLIDE_H_IN - LAYOUT_IN["body_y"] - 0.55) * 72)
    html = (
        _PLAYER_TEMPLATE
        .replace("%BG%", theme["bg"]).replace("%PANEL%", theme["panel"])
        .replace("%FG%", theme["fg"]).replace("%MUTED%", theme["muted"])
        .replace("%ACCENT%", theme["accent"]).replace("%ON_ACCENT%", theme["on_accent"])
        .replace("%FONT%", theme["font_stack"])
        .replace("%mx%", str(LAYOUT_PX["mx"])).replace("%body%", str(LAYOUT_PX["body_y"]))
        .replace("%imgh%", str(imgh))
        .replace("%DECK%", deck)
    )
    Path(path).write_text(html, encoding="utf-8")


# ---------------------------------------------------------------- entry point

def build_deck(arguments: dict, project_dir: Path):
    """Tool entry: validate outline, write <stem>.pptx + <stem>.preview.html.

    Returns {ok, path, preview, slides, warnings}; raises OutlineError on a
    bad outline so the tool result tells the model exactly what to fix.
    """
    stem, theme_name, clean, warnings = _clean_outline(arguments or {})
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = project_dir / f"{stem}.pptx"
    preview_path = project_dir / f"{stem}.preview.html"
    _render_pptx(pptx_path, theme_name, clean, project_dir, warnings)
    _render_player(preview_path, theme_name, clean, warnings)
    return {
        "ok": True,
        "path": pptx_path.name,
        "preview": preview_path.name,
        "slides": len(clean),
        "theme": theme_name,
        "warnings": warnings,
    }
