"""Plans a collision-safe output tree from a Trilium branch tree, converts
every note, and writes the result into an Obsidian vault folder.

No hardcoded destination map: paths are derived purely from the tree walk
(reader.walk) and each note's own title -- this is what makes the tool
generic rather than a one-off script tied to one person's taxonomy.
"""
from __future__ import annotations

import mimetypes
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import convert, frontmatter
from .reader import TreeNode, get_attachments, get_attributes, get_blob, get_note, walk

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def slugify(title: str) -> str:
    cleaned = _INVALID_CHARS.sub("-", title).strip()
    return cleaned or "untitled"


@dataclass
class PlannedPath:
    folder: Path  # where this note's own file(s)/children live
    md_path: Path  # this note's own markdown file, if it has content
    is_container: bool
    name: str


@dataclass
class MigrationSummary:
    migrated: int = 0
    binary: int = 0
    unsupported: Counter = field(default_factory=Counter)
    tables_flagged: list[str] = field(default_factory=list)
    skipped_empty: int = 0


def plan_paths(nodes: list[TreeNode], root_id: str, base_dir: Path) -> dict[str, PlannedPath]:
    children_count = Counter(n.parent_id for n in nodes)
    dest_dir: dict[str, Path] = {root_id: base_dir}
    used_names: dict[str, set] = defaultdict(set)
    plan: dict[str, PlannedPath] = {}

    for node in nodes:
        parent_dir = dest_dir.get(node.parent_id, base_dir)
        is_container = children_count.get(node.note_id, 0) > 0
        base_name = slugify(node.title)
        key = str(parent_dir)
        name = base_name
        i = 2
        while name in used_names[key]:
            name = f"{base_name} ({i})"
            i += 1
        used_names[key].add(name)

        if is_container:
            folder = parent_dir / name
            dest_dir[node.note_id] = folder
            md_path = folder / f"{name}.md"
        else:
            folder = parent_dir
            md_path = parent_dir / f"{name}.md"

        plan[node.note_id] = PlannedPath(folder=folder, md_path=md_path, is_container=is_container, name=name)

    return plan


def _ext_for_binary(title: str, mime: str) -> str:
    existing = Path(title).suffix
    if existing:
        return existing
    guessed = mimetypes.guess_extension(mime or "") or ".bin"
    return guessed


def _dedupe_image_names(base_stem: str, titles: list[str]) -> list[str]:
    counts = Counter(titles)
    seen: dict[str, int] = {}
    names = []
    for title in titles:
        if counts[title] > 1:
            seen[title] = seen.get(title, 0) + 1
            ext = Path(title).suffix or ".png"
            names.append(f"{base_stem} - img{seen[title]}{ext}")
        else:
            names.append(f"{base_stem} - {title}")
    return names


def migrate(con, output_dir: Path, root_id: str = "root", exclude: frozenset = frozenset(), dry_run: bool = False) -> MigrationSummary:
    nodes = list(walk(con, root_id=root_id, exclude=exclude))
    plan = plan_paths(nodes, root_id, output_dir)
    summary = MigrationSummary()

    # Pass 1: resolve which notes actually land in the output, for relation
    # (wikilink) resolution -- a relation only becomes a link if its target
    # was migrated in this same run.
    note_ids = {n.note_id for n in nodes}

    def resolve_relation(target_note_id: str) -> str | None:
        if target_note_id not in note_ids:
            return None
        target_plan = plan.get(target_note_id)
        return target_plan.name if target_plan else None

    for node in nodes:
        note = get_note(con, node.note_id)
        if note is None:
            continue
        node_plan = plan[node.note_id]

        attachments = get_attachments(con, node.note_id)
        result = convert.convert_note(note, attachments)

        if result.kind == "unsupported":
            summary.unsupported[note.type] += 1
            if dry_run:
                continue
            node_plan.folder.mkdir(parents=True, exist_ok=True)
            _write_unsupported_stub(node_plan, note)
            continue

        if result.kind == "binary":
            summary.binary += 1
            if dry_run:
                continue
            node_plan.folder.mkdir(parents=True, exist_ok=True)
            _write_binary_note(con, node_plan, note)
            continue

        # result.kind == "markdown"
        body = result.body
        if not body.strip() and not result.image_refs:
            summary.skipped_empty += 1
            continue

        if result.has_table:
            summary.tables_flagged.append(str(node_plan.md_path))

        summary.migrated += 1
        if dry_run:
            continue

        node_plan.folder.mkdir(parents=True, exist_ok=True)
        attrs = get_attributes(con, node.note_id)
        fields = {
            "source": "trilium2obsidian",
            "created": (note.date_created or "")[:10],
            "modified": (note.date_modified or "")[:10],
        }
        fields.update(frontmatter.build_frontmatter(attrs, resolve_relation))

        if result.image_refs:
            # Dedup by title (Trilium names every pasted image "image.png",
            # so titles collide) but resolve each ref's actual bytes by its
            # attachment_id -- titles alone can't distinguish which blob is
            # which.
            titles = [ref.attachment_title for ref in result.image_refs]
            names = _dedupe_image_names(node_plan.name, titles)
            by_attachment_id = {a.attachment_id: a for a in attachments}
            for ref, filename in zip(result.image_refs, names):
                body = body.replace(ref.placeholder, f"![[{filename}]]")
                att = by_attachment_id.get(ref.attachment_id)
                if att:
                    data = get_blob(con, att.blob_id)
                    _write_bytes(node_plan.folder / filename, data)

        if result.has_table:
            body = "<!-- trilium2obsidian: table below is auto-converted; please spot-check -->\n\n" + body

        text = frontmatter.render_frontmatter(fields) + f"\n\n# {note.title}\n\n{body}\n"
        node_plan.md_path.write_text(text, encoding="utf-8")

    return summary


def _find_blob_id(con, note_id: str) -> str | None:
    cur = con.cursor()
    cur.execute("select blobId from notes where noteId = ?", (note_id,))
    row = cur.fetchone()
    return row[0] if row else None


def _write_binary_note(con, node_plan: PlannedPath, note) -> None:
    blob_id = _find_blob_id(con, note.note_id)
    data = get_blob(con, blob_id) if blob_id else None
    if data is None:
        return
    ext = _ext_for_binary(note.title, note.mime)
    safe_title = slugify(note.title)
    filename = safe_title if Path(safe_title).suffix else f"{safe_title}{ext}"
    _write_bytes(node_plan.folder / filename, data)


def _write_bytes(path: Path, data) -> None:
    if data is None:
        return
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _write_unsupported_stub(node_plan: PlannedPath, note) -> None:
    stub = (
        frontmatter.render_frontmatter(
            {"source": "trilium2obsidian", "trilium_type": note.type, "converted": False}
        )
        + f"\n\n# {note.title}\n\n"
        + f"This was a Trilium `{note.type}` note. trilium2obsidian doesn't convert this "
        + "note type (see README) -- the original content is preserved alongside this file.\n"
    )
    node_plan.md_path.write_text(stub, encoding="utf-8")

    sidecar_ext = ".json" if note.mime and "json" in note.mime else ".txt"
    sidecar_path = node_plan.folder / f"{node_plan.name}.trilium-{note.type}{sidecar_ext}"
    _write_bytes(sidecar_path, note.content)
