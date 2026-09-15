"""Read-only access to a Trilium `document.db` SQLite backup.

Never writes to the database. Every query goes through a connection opened
in SQLite's `mode=ro` URI form, so even a bug here can't corrupt the
source backup.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# Trilium's hidden-notes subtree always uses this fixed noteId, on every
# install/version -- it holds UI scaffolding (launch bar, options panels,
# search/SQL console history), never user content, so it's excluded by
# default regardless of --root/--exclude.
HIDDEN_ROOT_ID = "_hidden"

DEFAULT_ROOT_ID = "root"


@dataclass
class NoteRecord:
    note_id: str
    title: str
    type: str
    mime: str
    date_created: str
    date_modified: str
    content: object  # str or bytes, from blobs.content; None if no blob


@dataclass
class AttachmentRecord:
    attachment_id: str
    owner_id: str
    title: str
    mime: str
    blob_id: str


@dataclass
class AttributeRecord:
    attribute_id: str
    note_id: str
    type: str  # "label" or "relation"
    name: str
    value: str
    is_inheritable: bool


@dataclass
class TreeNode:
    note_id: str
    parent_id: str
    title: str
    type: str
    mime: str
    position: int
    depth: int
    children: list = field(default_factory=list)


def connect(db_path: str) -> sqlite3.Connection:
    """Open the backup read-only. Raises if the path doesn't exist."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def list_roots(con: sqlite3.Connection, root_id: str = DEFAULT_ROOT_ID) -> list[dict]:
    """Direct children of `root_id`, with a recursive note count each.

    Used by the `list-roots` CLI subcommand so a user can see what's in
    their backup (e.g. "Trilium Demo (230 notes)") and decide what to
    include/exclude before running a real migration.
    """
    cur = con.cursor()
    cur.execute(
        "select b.noteId, n.title, n.type from branches b "
        "join notes n on n.noteId = b.noteId "
        "where b.parentNoteId = ? and b.isDeleted = 0 and n.isDeleted = 0 "
        "order by b.notePosition",
        (root_id,),
    )
    roots = []
    for note_id, title, note_type in cur.fetchall():
        if note_id == HIDDEN_ROOT_ID:
            continue  # always excluded from migration; not a real choice to surface
        count = sum(1 for _ in walk(con, root_id=note_id, exclude=frozenset()))
        roots.append({"note_id": note_id, "title": title, "type": note_type, "count": count})
    return roots


def walk(
    con: sqlite3.Connection,
    root_id: str = DEFAULT_ROOT_ID,
    exclude: frozenset[str] = frozenset(),
):
    """Depth-first walk of the branch tree from `root_id`, yielding
    TreeNode for every non-deleted note reachable (root itself excluded).

    Always excludes HIDDEN_ROOT_ID and anything in `exclude`, and their
    entire subtrees. Guards against cycles (clones can in principle form
    one) via a `seen` set, since Trilium notes can have multiple parents.
    """
    always_exclude = exclude | {HIDDEN_ROOT_ID}
    cur = con.cursor()
    seen: set[str] = set()

    def _walk(parent_id: str, depth: int):
        cur.execute(
            "select b.noteId, n.title, n.type, n.mime, b.notePosition "
            "from branches b join notes n on n.noteId = b.noteId "
            "where b.parentNoteId = ? and b.isDeleted = 0 and n.isDeleted = 0 "
            "order by b.notePosition",
            (parent_id,),
        )
        for note_id, title, note_type, mime, position in cur.fetchall():
            if note_id in always_exclude or note_id in seen:
                continue
            seen.add(note_id)
            yield TreeNode(
                note_id=note_id,
                parent_id=parent_id,
                title=title,
                type=note_type,
                mime=mime,
                position=position,
                depth=depth,
            )
            yield from _walk(note_id, depth + 1)

    yield from _walk(root_id, 0)


def get_note(con: sqlite3.Connection, note_id: str) -> NoteRecord | None:
    cur = con.cursor()
    cur.execute(
        "select n.title, n.type, n.mime, n.dateCreated, n.dateModified, bl.content "
        "from notes n left join blobs bl on bl.blobId = n.blobId "
        "where n.noteId = ?",
        (note_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    title, note_type, mime, created, modified, content = row
    return NoteRecord(
        note_id=note_id,
        title=title,
        type=note_type,
        mime=mime,
        date_created=created,
        date_modified=modified,
        content=content,
    )


def get_attachments(con: sqlite3.Connection, note_id: str) -> list[AttachmentRecord]:
    cur = con.cursor()
    cur.execute(
        "select attachmentId, ownerId, title, mime, blobId "
        "from attachments where ownerId = ? and isDeleted = 0",
        (note_id,),
    )
    return [
        AttachmentRecord(attachment_id=r[0], owner_id=r[1], title=r[2], mime=r[3], blob_id=r[4])
        for r in cur.fetchall()
    ]


def get_attributes(con: sqlite3.Connection, note_id: str) -> list[AttributeRecord]:
    cur = con.cursor()
    cur.execute(
        "select attributeId, noteId, type, name, value, isInheritable "
        "from attributes where noteId = ? and isDeleted = 0 "
        "order by position",
        (note_id,),
    )
    return [
        AttributeRecord(
            attribute_id=r[0], note_id=r[1], type=r[2], name=r[3], value=r[4], is_inheritable=bool(r[5])
        )
        for r in cur.fetchall()
    ]


def get_blob(con: sqlite3.Connection, blob_id: str):
    cur = con.cursor()
    cur.execute("select content from blobs where blobId = ?", (blob_id,))
    row = cur.fetchone()
    return row[0] if row else None
