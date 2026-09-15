from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import reader, writer


def _cmd_list_roots(args: argparse.Namespace) -> int:
    con = reader.connect(args.db_path)
    roots = reader.list_roots(con, root_id=args.root)
    print(f"{'noteId':<14} {'count':>6}  title")
    print("-" * 50)
    for r in roots:
        print(f"{r['note_id']:<14} {r['count']:>6}  {r['title']}")
    print()
    print("Pass --root <noteId> to scope a migration to one of these, or")
    print("--exclude <noteId> (repeatable) to skip one, e.g. demo content.")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    con = reader.connect(args.db_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = writer.migrate(
        con,
        output_dir,
        root_id=args.root,
        exclude=frozenset(args.exclude or []),
        dry_run=args.dry_run,
    )

    label = "Would migrate" if args.dry_run else "Migrated"
    print(f"{label} {summary.migrated} notes, {summary.binary} binary files.")
    if summary.skipped_empty:
        print(f"Skipped {summary.skipped_empty} empty organizational notes (no content of their own).")
    if summary.tables_flagged:
        print(f"\n{len(summary.tables_flagged)} note(s) had tables auto-converted -- spot-check these:")
        for path in summary.tables_flagged:
            print(f"  - {path}")
    if summary.unsupported:
        print("\nUnsupported note types (stub + raw content written, not converted):")
        for note_type, count in summary.unsupported.items():
            print(f"  - {note_type}: {count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trilium2obsidian")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-roots", help="List top-level branches in the backup, with note counts")
    p_list.add_argument("db_path", help="Path to a Trilium document.db backup")
    p_list.add_argument("--root", default="root", help="noteId to list children of (default: root)")
    p_list.set_defaults(func=_cmd_list_roots)

    p_migrate = sub.add_parser("migrate", help="Convert a Trilium backup into an Obsidian vault folder")
    p_migrate.add_argument("db_path", help="Path to a Trilium document.db backup")
    p_migrate.add_argument("output_dir", help="Directory to write the Obsidian-ready tree into")
    p_migrate.add_argument("--root", default="root", help="noteId to migrate from (default: root, i.e. everything)")
    p_migrate.add_argument(
        "--exclude", action="append", metavar="NOTE_ID",
        help="noteId to skip (with its whole subtree); repeatable. See `list-roots`.",
    )
    p_migrate.add_argument("--dry-run", action="store_true", help="Print what would be written, without writing")
    p_migrate.set_defaults(func=_cmd_migrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
