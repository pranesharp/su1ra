"""Document text extraction for the file-import feature (Tier 2).

Design notes
------------
- Plain-text formats (code, txt, md, csv, json, html, ...) need NO parser: the
  file *is* text. One generic path covers every language, forever — we do not
  implement per-language parsers.
- Binary/structured formats (pdf, docx, pptx, xlsx) use pure-Python libraries,
  imported lazily so a missing lib degrades to a clear message instead of
  breaking app boot.
- Every extractor returns a dict: {"text", "kind", "meta", "truncated"}.
  `meta` carries page/slide/sheet counts where meaningful.
"""

from pathlib import Path
import re

# Hard cap on extracted characters kept in memory / the DB. A 500-page PDF can
# be millions of chars; we keep a generous ceiling and mark it truncated.
MAX_EXTRACT_CHARS = 400_000

# Extensions handled by reading the file as text (no parser, no per-language code).
TEXT_EXTS = {
    # documents / data
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".xml", ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".tex", ".bib", ".rtf",
    # code
    ".py", ".pyw", ".ipynb", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".cs", ".java",
    ".kt", ".kts", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r",
    ".m", ".mm", ".swift", ".scala", ".dart", ".jl", ".hs", ".clj",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".gql", ".proto", ".dockerfile", ".makefile",
    ".asm", ".s", ".v", ".vhd", ".sv", ".vue", ".svelte",
}

# Extension -> (mime, kind label) for the binary/structured parsers.
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
PPTX_EXTS = {".pptx"}
XLSX_EXTS = {".xlsx", ".xlsm"}

DOCUMENT_EXTS = TEXT_EXTS | PDF_EXTS | DOCX_EXTS | PPTX_EXTS | XLSX_EXTS

# MIME types the upload endpoint will accept for documents.
DOCUMENT_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "text/plain", "text/markdown", "text/csv", "text/tab-separated-values",
    "text/html", "text/xml", "text/css", "text/x-python", "text/javascript",
    "application/json", "application/xml", "application/x-yaml",
    "application/octet-stream",  # browsers often send this for code files
}


def _cap(text):
    if len(text) > MAX_EXTRACT_CHARS:
        return text[:MAX_EXTRACT_CHARS], True
    return text, False


def _decode(raw):
    """Decode bytes as text, trying utf-8 then a couple of fallbacks."""
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_text_file(path):
    text = _decode(Path(path).read_bytes())
    text, truncated = _cap(text)
    return {"text": text, "kind": "text", "meta": {}, "truncated": truncated}


def _extract_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF support needs the 'pypdf' package (pip install pypdf)")
    reader = PdfReader(path)
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text, truncated = _cap("\n\n".join(parts))
    return {"text": text, "kind": "pdf", "meta": {"pages": len(reader.pages)}, "truncated": truncated}


def _extract_docx(path):
    try:
        import docx  # python-docx
    except ImportError:
        raise RuntimeError("Word support needs the 'python-docx' package (pip install python-docx)")
    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs]
    # Tables are common in school docs — flatten them row by row.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text, truncated = _cap("\n".join(parts))
    return {"text": text, "kind": "docx", "meta": {"paragraphs": len(document.paragraphs)}, "truncated": truncated}


def _extract_pptx(path):
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("PowerPoint support needs the 'python-pptx' package (pip install python-pptx)")
    prs = Presentation(path)
    parts = []
    for i, slide in enumerate(prs.slides, start=1):
        parts.append(f"--- Slide {i} ---")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs)
                    if line.strip():
                        parts.append(line)
            if shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
    text, truncated = _cap("\n".join(parts))
    return {"text": text, "kind": "pptx", "meta": {"slides": len(prs.slides)}, "truncated": truncated}


def _extract_xlsx(path):
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("Excel support needs the 'openpyxl' package (pip install openpyxl)")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"--- Sheet: {ws.title} ---")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                parts.append(" | ".join(cells))
    text, truncated = _cap("\n".join(parts))
    return {"text": text, "kind": "xlsx", "meta": {"sheets": len(wb.worksheets)}, "truncated": truncated}


def extract(path, filename=""):
    """Extract text from a document file. Returns {text, kind, meta, truncated}.

    Raises RuntimeError with a friendly message for unsupported types or
    missing optional dependencies.
    """
    ext = Path(filename or path).suffix.lower()
    if ext in PDF_EXTS:
        return _extract_pdf(path)
    if ext in DOCX_EXTS:
        return _extract_docx(path)
    if ext in PPTX_EXTS:
        return _extract_pptx(path)
    if ext in XLSX_EXTS:
        return _extract_xlsx(path)
    if ext in TEXT_EXTS:
        return _extract_text_file(path)
    raise RuntimeError(f"unsupported document type: {ext or '(no extension)'}")


def is_document_ext(ext):
    return ext.lower() in DOCUMENT_EXTS


# --- Remote page fetch (browser pane "summarize page") ----------------------
# The browser pane shows pages in an iframe; the backend can *also* fetch them
# over HTTP and extract text. Note the two are independent: a site may refuse
# framing (X-Frame-Options) yet still be fetchable, and a JS-rendered site may
# frame fine yet yield almost no text here.

PAGE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Below this many extracted chars we treat the page as JS-rendered / empty.
MIN_USABLE_PAGE_CHARS = 200


def _frame_headers(headers):
    """Return (frameable, reason) from a response's framing headers."""
    xfo = (headers.get("x-frame-options") or "").strip().lower()
    csp = headers.get("content-security-policy") or ""
    fa = ""
    for part in csp.split(";"):
        if "frame-ancestors" in part:
            fa = part.strip().lower()
    if xfo in ("deny", "sameorigin") or fa:
        return False, xfo or fa
    return True, ""


def page_info(url):
    """Cheaply probe a URL: is it frameable, and does it have usable text?

    Returns {frameable, frame_reason, fetchable, kind, chars, title}.
    Never raises — network problems come back as fetchable=False.
    """
    import httpx

    out = {"frameable": True, "frame_reason": "", "fetchable": False,
           "kind": "unknown", "chars": 0, "title": ""}
    try:
        resp = httpx.get(url, headers={"User-Agent": PAGE_USER_AGENT},
                         follow_redirects=True, timeout=15.0)
    except Exception:
        return out

    out["fetchable"] = resp.status_code < 400
    frameable, reason = _frame_headers(resp.headers)
    out["frameable"] = frameable
    out["frame_reason"] = reason

    ctype = (resp.headers.get("content-type") or "").lower()
    if "html" not in ctype:
        out["kind"] = "binary"
        return out

    text = html_to_text(resp.text)
    out["chars"] = len(text)
    out["kind"] = "html" if len(text) >= MIN_USABLE_PAGE_CHARS else "js"
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S)
    if m:
        out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    return out


def html_to_text(html):
    """Strip tags/scripts/styles from HTML and return readable text."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback: crude regex strip so the feature degrades, not breaks.
        html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "head"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def fetch_page_text(url, max_chars=12000):
    """Fetch a URL and return {text, title, url, truncated, js_rendered}.

    Raises RuntimeError with a friendly message on network failure.
    """
    import httpx

    try:
        resp = httpx.get(url, headers={"User-Agent": PAGE_USER_AGENT},
                         follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"could not fetch page: {exc}")

    ctype = (resp.headers.get("content-type") or "").lower()
    if "html" not in ctype:
        raise RuntimeError(f"not an HTML page ({ctype or 'unknown type'})")

    text = html_to_text(resp.text)
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:200]

    js_rendered = len(text) < MIN_USABLE_PAGE_CHARS
    truncated = len(text) > max_chars
    return {
        "text": text[:max_chars],
        "title": title,
        "url": url,
        "truncated": truncated,
        "js_rendered": js_rendered,
    }
