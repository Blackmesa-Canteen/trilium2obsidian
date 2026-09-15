from trilium2obsidian import convert
from trilium2obsidian.reader import NoteRecord


def test_table_html_to_markdown_basic():
    html = "<table><tr><th>Col A</th><th>Col B</th></tr><tr><td>1</td><td>pipe | test</td></tr></table>"
    md = convert.table_html_to_markdown(html)
    lines = md.splitlines()
    assert lines[0] == "| Col A | Col B |"
    assert lines[1] == "| --- | --- |"
    assert "pipe \\| test" in lines[2]


def test_table_html_to_markdown_uneven_rows_padded():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>only one</td></tr></table>"
    md = convert.table_html_to_markdown(html)
    lines = md.splitlines()
    assert lines[2] == "| only one |  |"


def test_convert_text_html_code_block_language_mapped():
    html = '<pre><code class="language-application-javascript-env-backend">const x = 1;</code></pre>'
    md, refs, has_table = convert.convert_text_html(html, [])
    assert "```javascript" in md
    assert "const x = 1;" in md
    assert not has_table


def test_convert_text_html_detects_table():
    html = "<p>x</p><table><tr><td>a</td></tr></table>"
    _, _, has_table = convert.convert_text_html(html, [])
    assert has_table


def test_convert_text_html_uses_dash_bullets():
    html = "<ul><li>one</li><li>two</li></ul>"
    md, _, _ = convert.convert_text_html(html, [])
    assert "- one" in md
    assert "* one" not in md


def test_convert_note_code_type():
    note = NoteRecord("n1", "T", "code", "application/json", "", "", '{"a": 1}')
    result = convert.convert_note(note, [])
    assert result.kind == "markdown"
    assert result.body == '```json\n{"a": 1}\n```'


def test_convert_note_mermaid_type():
    note = NoteRecord("n1", "T", "mermaid", "text/vnd.mermaid", "", "", "graph TD; A-->B;")
    result = convert.convert_note(note, [])
    assert result.kind == "markdown"
    assert result.body.startswith("```mermaid\n")


def test_convert_note_unsupported_type():
    note = NoteRecord("n1", "T", "canvas", "application/json", "", "", "{}")
    result = convert.convert_note(note, [])
    assert result.kind == "unsupported"


def test_mime_to_lang_fallback():
    assert convert.mime_to_lang("text/x-ruby") == "ruby"
    assert convert.mime_to_lang("application/json") == "json"
