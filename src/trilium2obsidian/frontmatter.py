"""Trilium attributes (labels/relations) -> Obsidian YAML frontmatter.

No PyYAML dependency -- frontmatter here is a small, fully-controlled
subset (string scalars and lists of strings), so a hand-rolled, safe
serializer avoids pulling in a dependency for it.
"""
from __future__ import annotations

from typing import Callable

from .reader import AttributeRecord

# Trilium-internal label names: UI wiring, not meaningful to a person
# reading their own notes. Confirmed against a real backup's attribute
# survey this project was built from -- anything not in this list is
# treated as a real user label and passed through.
LABEL_DENYLIST = {
    "iconClass",
    "cssClass",
    "sorted",
    "dateNote",
    "monthNote",
    "yearNote",
    "builtinWidget",
    "launcherType",
    "command",
    "desktopOnly",
    "keepCurrentHoisting",
    "customResourceProvider",
    "bookZoomLevel",
    "baseSize",
    "growthFactor",
    "excludeFromNoteMap",
    "label:keyboardShortcut",
    "workspace",
    "viewType",
    "pageSize",
    "hideHighlightWidget",
}

# Trilium-internal relation names: rendering/template wiring, not
# cross-note relationships a person authored.
RELATION_DENYLIST = {
    "template",
    "child:template",
    "child:child:template",
    "renderNote",
    "relationMapLink",
}

RESERVED_KEYS = {"domain", "category", "project", "source", "created", "modified"}


def build_frontmatter(
    attributes: list[AttributeRecord],
    resolve_relation_target: Callable[[str], str | None],
) -> dict[str, object]:
    """Fold a note's labels/relations into a frontmatter dict.

    Repeated label names become a list. Relations resolve to `[[target]]`
    wikilinks via `resolve_relation_target(target_note_id)`, which the
    caller wires to the migration's noteId -> destination-path map; a
    relation whose target wasn't migrated in this run is dropped (there's
    nothing to link to) rather than left as a raw internal noteId.
    """
    fields: dict[str, object] = {}

    for attr in attributes:
        if attr.type == "label":
            if attr.name in LABEL_DENYLIST or attr.name in RESERVED_KEYS:
                continue
            value: object = attr.value if attr.value else True
        elif attr.type == "relation":
            if attr.name in RELATION_DENYLIST:
                continue
            target = resolve_relation_target(attr.value)
            if not target:
                continue
            value = f"[[{target}]]"
        else:
            continue

        if attr.name in fields:
            existing = fields[attr.name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                fields[attr.name] = [existing, value]
        else:
            fields[attr.name] = value

    return fields


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "" or any(ch in text for ch in ':#[]{}"\'') or text.strip() != text:
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


def render_frontmatter(fields: dict[str, object]) -> str:
    """Render an ordered dict as a `---`-delimited YAML frontmatter block."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)
