"""Builds a tiny synthetic Trilium `document.db`-shaped SQLite fixture.

Deliberately NOT the user's real backup -- a small, purpose-built tree
covering every case the converter needs to handle:

root
 |- Folder A            (container, no content of its own)
 |   |- Note With Table   (text, has a <table>)
 |   `- Note With Images  (text, 2 images both titled "image.png" -- the
 |                          collision case)
 |- Note With Code Block  (text, <pre><code class="language-application-json">)
 |- A Code Note            (type=code, mime=application/json)
 |- A Mermaid Note          (type=mermaid)
 |- A Canvas Note            (type=canvas -- unsupported, must not be dropped)
 |- Duplicate               (text, title collides with its sibling below)
 |- Duplicate               (text, same title, different noteId)
 `- Labeled Note              (text, has label attributes + a denylisted one)

_hidden                    (system root -- must always be excluded)
 `- Some UI Note
"""
from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

SCHEMA = textwrap.dedent(
    """
    CREATE TABLE notes (
        noteId TEXT NOT NULL PRIMARY KEY,
        title TEXT NOT NULL,
        isProtected INT NOT NULL DEFAULT 0,
        type TEXT NOT NULL DEFAULT 'text',
        mime TEXT NOT NULL DEFAULT 'text/html',
        blobId TEXT,
        isDeleted INT NOT NULL DEFAULT 0,
        dateCreated TEXT NOT NULL,
        dateModified TEXT NOT NULL
    );
    CREATE TABLE branches (
        branchId TEXT NOT NULL PRIMARY KEY,
        noteId TEXT NOT NULL,
        parentNoteId TEXT NOT NULL,
        notePosition INTEGER NOT NULL,
        isDeleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE attributes (
        attributeId TEXT NOT NULL PRIMARY KEY,
        noteId TEXT NOT NULL,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        value TEXT NOT NULL DEFAULT '',
        position INT NOT NULL DEFAULT 0,
        isDeleted INT NOT NULL DEFAULT 0,
        isInheritable INT DEFAULT 0
    );
    CREATE TABLE blobs (
        blobId TEXT NOT NULL PRIMARY KEY,
        content BLOB
    );
    CREATE TABLE attachments (
        attachmentId TEXT NOT NULL PRIMARY KEY,
        ownerId TEXT NOT NULL,
        role TEXT NOT NULL,
        mime TEXT NOT NULL,
        title TEXT NOT NULL,
        blobId TEXT,
        isDeleted INT NOT NULL DEFAULT 0
    );
    """
)


def _note(cur, note_id, title, note_type="text", mime="text/html", content=None, blob_id=None):
    if content is not None and blob_id is None:
        blob_id = f"blob-{note_id}"
        cur.execute("INSERT INTO blobs (blobId, content) VALUES (?, ?)", (blob_id, content))
    cur.execute(
        "INSERT INTO notes (noteId, title, type, mime, blobId, dateCreated, dateModified) "
        "VALUES (?, ?, ?, ?, ?, '2024-01-01 00:00:00', '2024-01-02 00:00:00')",
        (note_id, title, note_type, mime, blob_id),
    )


def _branch(cur, note_id, parent_id, position):
    cur.execute(
        "INSERT INTO branches (branchId, noteId, parentNoteId, notePosition) VALUES (?, ?, ?, ?)",
        (f"br-{note_id}-{parent_id}", note_id, parent_id, position),
    )


def _attachment(cur, attachment_id, owner_id, title, content, mime="image/png"):
    blob_id = f"blob-{attachment_id}"
    cur.execute("INSERT INTO blobs (blobId, content) VALUES (?, ?)", (blob_id, content))
    cur.execute(
        "INSERT INTO attachments (attachmentId, ownerId, role, mime, title, blobId) "
        "VALUES (?, ?, 'image', ?, ?, ?)",
        (attachment_id, owner_id, mime, title, blob_id),
    )


def _label(cur, attr_id, note_id, name, value=""):
    cur.execute(
        "INSERT INTO attributes (attributeId, noteId, type, name, value) VALUES (?, ?, 'label', ?, ?)",
        (attr_id, note_id, name, value),
    )


@pytest.fixture
def fixture_db_path(tmp_path: Path) -> str:
    db_path = tmp_path / "fixture.db"
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    # root's children
    _note(cur, "folderA", "Folder A", content="<p></p>")
    _branch(cur, "folderA", "root", 0)

    _note(
        cur,
        "noteTable",
        "Note With Table",
        content=(
            "<p>intro</p>"
            "<table><tr><th>Col A</th><th>Col B</th></tr>"
            "<tr><td>1</td><td>pipe | test</td></tr></table>"
        ),
    )
    _branch(cur, "noteTable", "folderA", 0)

    _note(
        cur,
        "noteImages",
        "Note With Images",
        content=(
            '<p>see</p><img src="api/attachments/att1/image/image.png">'
            '<img src="api/attachments/att2/image/image.png">'
        ),
    )
    _branch(cur, "noteImages", "folderA", 1)
    _attachment(cur, "att1", "noteImages", "image.png", b"\xff\xd8\xff\xe0FAKEJPEG1")
    _attachment(cur, "att2", "noteImages", "image.png", b"\xff\xd8\xff\xe0FAKEJPEG2")

    _note(
        cur,
        "noteCode",
        "Note With Code Block",
        content='<pre><code class="language-application-json">{"a": 1}</code></pre>',
    )
    _branch(cur, "noteCode", "root", 1)

    _note(cur, "codeNote", "A Code Note", note_type="code", mime="application/json", content='{"b": 2}')
    _branch(cur, "codeNote", "root", 2)

    _note(cur, "mermaidNote", "A Mermaid Note", note_type="mermaid", content="graph TD; A-->B;")
    _branch(cur, "mermaidNote", "root", 3)

    _note(cur, "canvasNote", "A Canvas Note", note_type="canvas", mime="application/json", content='{"elements": []}')
    _branch(cur, "canvasNote", "root", 4)

    _note(cur, "dup1", "Duplicate", content="<p>first</p>")
    _branch(cur, "dup1", "root", 5)
    _note(cur, "dup2", "Duplicate", content="<p>second</p>")
    _branch(cur, "dup2", "root", 6)

    _note(cur, "labeled", "Labeled Note", content="<p>hi</p>")
    _branch(cur, "labeled", "root", 7)
    _label(cur, "attr1", "labeled", "topic", "testing")
    _label(cur, "attr2", "labeled", "iconClass", "bx bx-note")  # denylisted, must not surface

    # hidden system subtree -- must always be excluded
    _note(cur, "_hidden", "Hidden Notes", note_type="doc", content="<p></p>")
    _branch(cur, "_hidden", "root", 99)
    _note(cur, "uiNote", "Some UI Note", content="<p>should never appear</p>")
    _branch(cur, "uiNote", "_hidden", 0)

    con.commit()
    con.close()
    return str(db_path)
