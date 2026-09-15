"""Per-note-type conversion: Trilium note -> Markdown body (+ image refs).

Design note: table and image/code-block handling use a protect/restore
pattern around `html2text` rather than reimplementing headings/lists/links
from scratch -- html2text already gets those right (this is verified: it's
Trilium's own *native* export that mangles H2->bold and `-`->`*`, not
html2text). What html2text does NOT do well is tables (loses the header
separator) and code blocks (loses the language), so those two are handled
by dedicated, tested code here instead.
"""
from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import html2text

from .reader import AttachmentRecord, NoteRecord

# Note types with a clean, safe conversion path.
TEXT_TYPES = {"text"}
CODE_TYPES = {"code"}
MERMAID_TYPES = {"mermaid"}
BINARY_TYPES = {"image", "file"}
# Everything else (canvas, relationMap, mindMap, book, render, noteMap,
# search, launcher, contentWidget, doc, ...) has no clean Obsidian
# equivalent and is intentionally out of scope for v1 -- see README.

# CKEditor's `language-X` class on <pre><code> inside a `text` note's HTML,
# as actually emitted by Trilium's editor -> a normal fenced-code-block tag.
CODE_CLASS_LANG = {
    "text-plain": "",
    "application-json": "json",
    "application-javascript-env-backend": "javascript",
    "application-javascript-env-frontend": "javascript",
    "text-x-python": "python",
    "text-css": "css",
    "text-html": "html",
    "text-x-sh": "bash",
    "application-x-yaml": "yaml",
}

# `notes.mime` for type='code' notes -> fenced-code-block language.
MIME_LANG = {
    "application/javascript;env=frontend": "javascript",
    "application/javascript;env=backend": "javascript",
    "text/x-python": "python",
    "text/x-sqlite;schema=trilium": "sql",
    "text/css": "css",
    "text/html": "html",
    "application/json": "json",
    "text/x-sh": "bash",
    "application/x-yaml": "yaml",
    "text/x-csrc": "c",
    "text/x-c++src": "cpp",
    "text/x-java": "java",
}


def mime_to_lang(mime: str) -> str:
    if mime in MIME_LANG:
        return MIME_LANG[mime]
    # Fall back to the subtype, stripping any ";param=..." suffix and an
    # "x-" prefix (e.g. "text/x-ruby" -> "ruby").
    subtype = mime.split(";")[0].split("/")[-1]
    return subtype[2:] if subtype.startswith("x-") else subtype


def code_class_to_lang(class_attr: str) -> str:
    m = re.search(r"language-([\w-]+)", class_attr or "")
    if not m:
        return ""
    slug = m.group(1)
    return CODE_CLASS_LANG.get(slug, slug)


@dataclass
class ImageRef:
    """A reference to an image/file that lived inside a text note's HTML,
    resolved against that note's own attachments.

    Carries the real attachment_id (not just its title) because Trilium's
    CKEditor names every pasted image "image.png" -- multiple images in one
    note routinely share a title, so the title alone can't tell them apart.
    """
    attachment_id: str
    attachment_title: str
    placeholder: str


@dataclass
class ConversionResult:
    kind: str  # "markdown", "binary", "unsupported"
    body: str = ""
    image_refs: list[ImageRef] = field(default_factory=list)
    has_table: bool = False


# --- table conversion -------------------------------------------------


class _TableParser(HTMLParser):
    """Parses a single <table>...</table> fragment into rows of cells.
    colspan/rowspan are intentionally not modeled (documented limitation):
    a spanning cell's content is kept once, in a single column."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cur_row: list[str] | None = None
        self._cur_cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th"):
            self._cur_cell = []
            self._in_cell = True
        elif tag == "br" and self._in_cell:
            self._cur_cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "tr" and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None
        elif tag in ("td", "th") and self._in_cell:
            text = "".join(self._cur_cell).strip()
            text = re.sub(r"\s+", " ", text)
            text = text.replace("|", "\\|")
            self._cur_row.append(text)
            self._cur_cell = None
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell.append(data)


def table_html_to_markdown(table_html: str) -> str:
    parser = _TableParser()
    parser.feed(table_html)
    rows = [r for r in parser.rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join([" --- "] * width) + "|"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# --- text-note HTML -> markdown ----------------------------------------

_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
_PRE_CODE_RE = re.compile(
    r'<pre><code(?:\s+class="([^"]*)")?[^>]*>(.*?)</code></pre>', re.DOTALL
)
_IMG_RE = re.compile(r'<img[^>]*\bsrc="api/attachments/([^/"]+)/[^"]*"[^>]*>')


def _make_html2text() -> html2text.HTML2Text:
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_links = False
    h.ul_item_mark = "-"  # native Trilium export renders `*`; Obsidian community convention is `-`
    return h


def convert_text_html(raw_html: str, attachments: list[AttachmentRecord]) -> tuple[str, list[ImageRef], bool]:
    """Convert a `text`-type note's HTML body to Markdown.

    Returns (markdown, image_refs, has_table). image_refs reference
    attachments by title; the caller (writer) resolves them to real
    on-disk filenames since that requires knowledge of sibling notes'
    output paths for collision-avoidance.
    """
    by_attachment_id = {a.attachment_id: a for a in attachments}
    content = raw_html or ""
    has_table = bool(_TABLE_RE.search(content))

    tables: list[str] = []

    def _table_repl(m: re.Match) -> str:
        tables.append(table_html_to_markdown(m.group(0)))
        return f"@@T2O_TABLE_{len(tables) - 1}@@"

    content = _TABLE_RE.sub(_table_repl, content)

    code_blocks: list[str] = []

    def _code_repl(m: re.Match) -> str:
        lang = code_class_to_lang(m.group(1) or "")
        code = html_module.unescape(m.group(2))
        code = re.sub(r"<[^>]+>", "", code)  # strip stray inline tags CKEditor sometimes leaves
        code_blocks.append(f"```{lang}\n{code}\n```")
        return f"@@T2O_CODE_{len(code_blocks) - 1}@@"

    content = _PRE_CODE_RE.sub(_code_repl, content)

    image_refs: list[ImageRef] = []

    def _img_repl(m: re.Match) -> str:
        att = by_attachment_id.get(m.group(1))
        if not att:
            return ""
        placeholder = f"@@T2O_IMAGE_{len(image_refs)}@@"
        image_refs.append(ImageRef(attachment_id=att.attachment_id, attachment_title=att.title, placeholder=placeholder))
        return placeholder

    content = _IMG_RE.sub(_img_repl, content)

    md = _make_html2text().handle(content).strip()

    for i, table_md in enumerate(tables):
        md = md.replace(f"@@T2O_TABLE_{i}@@", f"\n{table_md}\n")
    for i, block in enumerate(code_blocks):
        md = md.replace(f"@@T2O_CODE_{i}@@", f"\n{block}\n")
    # image placeholders are left in place for the writer to substitute
    # with `![[resolved filename]]` once it knows the final on-disk name.

    return md, image_refs, has_table


def convert_note(note: NoteRecord, attachments: list[AttachmentRecord]) -> ConversionResult:
    if note.type in TEXT_TYPES:
        raw = note.content if isinstance(note.content, str) else (note.content or b"").decode("utf-8", "replace")
        md, image_refs, has_table = convert_text_html(raw, attachments)
        return ConversionResult(kind="markdown", body=md, image_refs=image_refs, has_table=has_table)

    if note.type in CODE_TYPES:
        raw = note.content if isinstance(note.content, str) else (note.content or b"").decode("utf-8", "replace")
        lang = mime_to_lang(note.mime)
        return ConversionResult(kind="markdown", body=f"```{lang}\n{raw}\n```")

    if note.type in MERMAID_TYPES:
        raw = note.content if isinstance(note.content, str) else (note.content or b"").decode("utf-8", "replace")
        return ConversionResult(kind="markdown", body=f"```mermaid\n{raw}\n```")

    if note.type in BINARY_TYPES:
        return ConversionResult(kind="binary")

    return ConversionResult(kind="unsupported")
