"""Shared schema definitions and helpers for Iraq School content tooling."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONTENT_DIR = REPO_ROOT / "content"
BOOKS_DIR = CONTENT_DIR / "books"
NOTES_DIR = CONTENT_DIR / "notes"
CATALOG_DIR = REPO_ROOT / "catalog"
TOOLS_DIR = REPO_ROOT / "tools"
LEGACY_DIR = REPO_ROOT / "legacy"
STATE_FILE = REPO_ROOT / ".catalog_state.json"
TAXONOMY_FILE = CONTENT_DIR / "taxonomy.json"
MIGRATION_REPORT = LEGACY_DIR / "migration_report.json"

SCHEMA_VERSION = 1

BOOK_ID_RE = re.compile(r"^(pri|int|prep)-grade-(\d+)-([a-z][a-z0-9-]*)-(\d+)$")
NOTE_ID_RE = re.compile(r"^note-(\d+)$")

STAGES = {"primary", "intermediate", "preparatory"}
PREP_BRANCHES = {"scientific", "literary", "vocational"}

BOOK_REQUIRED = [
    "id", "stage_id", "grade_id", "subject_id",
    "title", "title_en", "pdf_url",
]
NOTE_REQUIRED = ["id", "stage_id", "grade_id", "subject_id", "title", "pdf_url"]

BOOK_APP_FIELDS = [
    "id", "title", "title_en", "part", "parts_total", "description",
    "authors", "publisher", "year", "pages", "cover_url", "pdf_url",
    "metadata_url", "size_bytes", "asset_version", "asset_hash",
]
NOTE_APP_FIELDS = ["id", "title", "author", "pdf_url", "pages", "source", "source_url"]

BOOK_ADDITIVE_FIELDS = ["search_keys", "checksum", "license", "status"]
NOTE_ADDITIVE_FIELDS = ["search_keys", "license", "status"]

ALLOWED_STATUS = {"active", "broken", "removed", "pending"}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def read_manifests(kind: str) -> list[dict]:
    """Read all content manifests of a kind (books|notes), sorted by id."""
    d = BOOKS_DIR if kind == "books" else NOTES_DIR
    out = []
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_dir() and (p / "manifest.json").is_file():
                out.append(load_json(p / "manifest.json"))
    return out


def load_taxonomy() -> dict:
    if not TAXONOMY_FILE.is_file():
        raise SystemExit("content/taxonomy.json missing — run tools/ingest.py first")
    return load_json(TAXONOMY_FILE)


def validate_id_format(kind: str, book_id: str) -> bool:
    return bool((BOOK_ID_RE if kind == "books" else NOTE_ID_RE).match(book_id))


def find_taxonomy_path(tax: dict, m: dict) -> tuple[dict, dict, dict, dict] | None:
    """Resolve (stage, branch|None, grade, subject) from a manifest's ids."""
    for stage in tax["stages"]:
        if stage["id"] != m["stage_id"]:
            continue
        branch = None
        if m.get("branch_id"):
            for br in stage.get("branches", []):
                if br["id"] == m["branch_id"]:
                    branch = br
                    break
            if branch is None:
                return None
            grades = branch["grades"]
        else:
            grades = stage["grades"]
        for grade in grades:
            if grade["id"] == m["grade_id"]:
                subject = next(
                    (s for s in tax["subjects"] if s["id"] == m["subject_id"]), None
                )
                if subject is None:
                    return None
                return stage, branch, grade, subject
        return None
    return None