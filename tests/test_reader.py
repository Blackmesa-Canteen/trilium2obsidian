from trilium2obsidian import reader


def test_list_roots_excludes_hidden(fixture_db_path):
    con = reader.connect(fixture_db_path)
    roots = reader.list_roots(con)
    titles = {r["title"] for r in roots}
    assert "Hidden Notes" not in titles
    assert "Folder A" in titles
    folder_a = next(r for r in roots if r["title"] == "Folder A")
    assert folder_a["count"] == 2  # Note With Table + Note With Images


def test_walk_excludes_hidden_subtree(fixture_db_path):
    con = reader.connect(fixture_db_path)
    nodes = list(reader.walk(con))
    ids = {n.note_id for n in nodes}
    assert "_hidden" not in ids
    assert "uiNote" not in ids
    assert "folderA" in ids
    assert "noteTable" in ids


def test_walk_respects_exclude(fixture_db_path):
    con = reader.connect(fixture_db_path)
    nodes = list(reader.walk(con, exclude=frozenset({"folderA"})))
    ids = {n.note_id for n in nodes}
    assert "folderA" not in ids
    assert "noteTable" not in ids  # whole subtree excluded
    assert "codeNote" in ids


def test_get_note_and_attributes(fixture_db_path):
    con = reader.connect(fixture_db_path)
    note = reader.get_note(con, "labeled")
    assert note.title == "Labeled Note"
    attrs = reader.get_attributes(con, "labeled")
    names = {a.name for a in attrs}
    assert "topic" in names
    assert "iconClass" in names  # reader itself doesn't filter -- frontmatter.py does


def test_get_attachments(fixture_db_path):
    con = reader.connect(fixture_db_path)
    atts = reader.get_attachments(con, "noteImages")
    assert len(atts) == 2
    assert all(a.title == "image.png" for a in atts)
