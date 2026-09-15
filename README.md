# trilium2obsidian

Migrate a [Trilium Notes](https://github.com/TriliumNext/Trilium) SQLite
backup (`document.db`) into a plain Markdown tree ready to open as an
Obsidian vault. Generic: it walks your note tree and mirrors it — no
built-in opinion about folder structure, no taxonomy imposed.

Reads the backup file directly and read-only. No running Trilium server,
no ETAPI token, works offline.

## Why not just use Trilium's built-in export?

Trilium's own "export subtree as Markdown" already gets you most of the
way there. This tool exists to close the gaps in it:

| | Native Trilium export | trilium2obsidian |
|---|---|---|
| Headings | `##` becomes **bold** text | Real `#`/`##` headings |
| Bullet lists | `*` | `-` |
| Tables | Not supported ([open issue](https://github.com/TriliumNext/trilium/issues)) | Converted to GFM tables |
| Attachments with the same filename | Silently overwrite each other | Auto-disambiguated (`img1.png`, `img2.png`, ...) |
| Attributes (`#label`) | Dropped | Mapped to YAML frontmatter |
| Relations (`~relation`) | Dropped | Mapped to `[[wikilinks]]`, if the target was also migrated |
| Code notes / Mermaid notes | Not specifically handled | Fenced code blocks with language; Mermaid passed through natively |

## Scope and known limitations

| Note type | Handling |
|---|---|
| `text` | Converted to Markdown: headings, lists, links, code blocks, tables, images |
| `code` | Wrapped in a fenced code block, language inferred from MIME |
| `mermaid` | Passed through as a ` ```mermaid ` fence (Obsidian renders it natively) |
| `image` / `file` | Extracted as a binary file |
| `canvas`, `relationMap`, `mindMap`, `book`, `render`, `noteMap`, `search`, `launcher`, `contentWidget`, `doc` | **Not converted.** A stub note is written explaining why, plus the raw original content alongside it — nothing is silently dropped |

Other known limitations:
- Table cells are converted to plain text — inline formatting and links
  *inside* a table cell are flattened.
- `colspan`/`rowspan` are not modeled; a spanning cell's content lands in a
  single column.
- Trilium's built-in "Hidden Notes" subtree (launch bar, options panels,
  search history — never user content) is always excluded.

## Install

```bash
pip install trilium2obsidian
```

## Quickstart

```bash
# See what's in your backup before migrating anything
trilium2obsidian list-roots path/to/document.db

# Migrate everything except a subtree you don't want (e.g. demo content)
trilium2obsidian migrate path/to/document.db ./my-vault --exclude <noteId>

# Or scope to just one subtree
trilium2obsidian migrate path/to/document.db ./my-vault --root <noteId>
```

Point Obsidian at `./my-vault` (or copy its contents into an existing
vault) — there's no separate "import" step; the output is already a plain
folder of Markdown files.

## CLI reference

**`list-roots <db_path> [--root NOTE_ID]`**
Print the direct children of `root` (or `--root`) with a recursive note
count each, so you can decide what to include/exclude.

**`migrate <db_path> <output_dir> [--root NOTE_ID] [--exclude NOTE_ID]... [--dry-run]`**
- `--root` — migrate from this noteId instead of the whole tree.
- `--exclude` — skip a noteId and its subtree; repeatable.
- `--dry-run` — print what would be written without writing anything.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

Tests run against a small synthetic fixture database (`tests/conftest.py`)
— never against a real Trilium backup.

## License

MIT — see [LICENSE](LICENSE).
