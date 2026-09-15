from pathlib import Path

from trilium2obsidian import reader, writer


def _run_migrate(fixture_db_path, tmp_path):
    con = reader.connect(fixture_db_path)
    out = tmp_path / "vault"
    summary = writer.migrate(con, out)
    return out, summary


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_hidden_subtree_never_written(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    all_files = list(out.rglob("*"))
    names = {f.name for f in all_files}
    assert "Hidden Notes.md" not in names
    assert "Some UI Note.md" not in names


def test_table_note_converted(fixture_db_path, tmp_path):
    out, summary = _run_migrate(fixture_db_path, tmp_path)
    md_path = out / "Folder A" / "Note With Table.md"
    assert md_path.exists()
    text = _read(md_path)
    assert "| Col A | Col B |" in text
    assert "pipe \\| test" in text
    assert str(md_path) in summary.tables_flagged or "Note With Table.md" in "".join(summary.tables_flagged)


def test_colliding_image_filenames_disambiguated(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    folder = out / "Folder A"
    md_text = _read(folder / "Note With Images.md")
    assert "![[Note With Images - img1.png]]" in md_text
    assert "![[Note With Images - img2.png]]" in md_text
    assert (folder / "Note With Images - img1.png").exists()
    assert (folder / "Note With Images - img2.png").exists()
    img1 = (folder / "Note With Images - img1.png").read_bytes()
    img2 = (folder / "Note With Images - img2.png").read_bytes()
    assert img1 != img2  # not overwritten by each other


def test_code_block_note_converted(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    text = _read(out / "Note With Code Block.md")
    assert "```json" in text
    assert '{"a": 1}' in text


def test_code_type_note_converted(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    text = _read(out / "A Code Note.md")
    assert "```json" in text
    assert '{"b": 2}' in text


def test_mermaid_note_passthrough(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    text = _read(out / "A Mermaid Note.md")
    assert "```mermaid" in text
    assert "graph TD" in text


def test_unsupported_type_writes_stub_and_sidecar(fixture_db_path, tmp_path):
    out, summary = _run_migrate(fixture_db_path, tmp_path)
    stub = out / "A Canvas Note.md"
    assert stub.exists()
    text = _read(stub)
    assert "converted: false" in text
    assert "canvas" in text
    sidecar = out / "A Canvas Note.trilium-canvas.json"
    assert sidecar.exists()
    assert '"elements"' in _read(sidecar)
    assert summary.unsupported["canvas"] == 1


def test_duplicate_titles_disambiguated(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    assert (out / "Duplicate.md").exists()
    assert (out / "Duplicate (2).md").exists()
    first = _read(out / "Duplicate.md")
    second = _read(out / "Duplicate (2).md")
    assert first != second


def test_label_frontmatter_filters_denylist(fixture_db_path, tmp_path):
    out, _ = _run_migrate(fixture_db_path, tmp_path)
    text = _read(out / "Labeled Note.md")
    assert "topic: testing" in text
    assert "iconClass" not in text


def test_dry_run_writes_nothing(fixture_db_path, tmp_path):
    con = reader.connect(fixture_db_path)
    out = tmp_path / "vault"
    out.mkdir()
    summary = writer.migrate(con, out, dry_run=True)
    assert summary.migrated > 0
    assert not any(out.rglob("*.md"))
