"""Generate catalog/ artifacts from content/ manifests.

Deterministic + incremental:
- output bytes depend only on content inputs (sorted keys, compact JSON, stable order)
- per-file `version` bumps only when that file's bytes change
- `catalogVersion` bumps whenever any artifact changes
- .catalog_state.json (committed) tracks versions; sha256 is always recomputed

Run: python tools/build.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import (  # noqa: E402
    CATALOG_DIR, STATE_FILE, TAXONOMY_FILE, load_json, dump_json,
    read_manifests, load_taxonomy, find_taxonomy_path,
)
from normalize import search_keys  # noqa: E402

# Initial versions for the first post-migration build (bumped from live v4/v1/v1).
SEED_CATALOG_VERSION = 5
SEED_FILE_VERSIONS = {"books.json": 3, "notes.json": 2}

BOOK_APP_FIELDS = [
    "id", "title", "title_en", "part", "parts_total", "description",
    "authors", "publisher", "year", "pages", "cover_url", "pdf_url",
    "metadata_url", "size_bytes", "asset_version", "asset_hash",
]
NOTE_APP_FIELDS = ["id", "title", "author", "pdf_url", "pages", "source", "source_url"]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def emit_book_entry(m: dict, subject_name: str, grade_name: str) -> dict:
    e = {f: m.get(f) for f in BOOK_APP_FIELDS if m.get(f) is not None}
    e["authors"] = m.get("authors") or []
    if m.get("pdf_sha256"):
        e["checksum"] = m["pdf_sha256"]
    for f in ("license", "status"):
        if m.get(f):
            e[f] = m[f]
    return e


def emit_note_entry(m: dict, subject_name: str, grade_name: str) -> dict:
    e = {f: m.get(f) for f in NOTE_APP_FIELDS if m.get(f) not in (None, "")}
    for f in ("license", "status"):
        if m.get(f):
            e[f] = m[f]
    return e


def build_trees(tax: dict, books: list[dict], notes: list[dict]):
    """Return (books_stages, notes_stages, search_entries) with taxonomy order."""
    book_by_id = {m["id"]: m for m in books}
    note_by_id = {m["id"]: m for m in notes}
    books_placed: set[str] = set()
    notes_placed: set[str] = set()
    search_entries = []

    # Annotate manifests with taxonomy metadata + emitted entries.
    for m in books + notes:
        path = find_taxonomy_path(tax, m)
        if path is None:
            continue
        stage, branch, grade, subject = path
        m["_stage"], m["_branch"], m["_grade"], m["_subject"] = stage, branch, grade, subject
        keys = search_keys(
            m.get("title"), m.get("title_en"), m.get("author"), subject["name"],
            grade["name"], " ".join(m.get("authors") or []),
        )
        if m["id"] in book_by_id:
            e = emit_book_entry(m, subject["name"], grade["name"])
            m["_entry"] = e
            books_placed.add(m["id"])
            search_entries.append({
                "id": m["id"], "type": "book", "stage_id": stage["id"],
                "branch_id": branch["id"] if branch else None,
                "grade_id": grade["id"], "subject_id": subject["id"],
                "title": e.get("title", ""), "search_keys": keys,
            })
        if m["id"] in note_by_id:
            e = emit_note_entry(m, subject["name"], grade["name"])
            m["_entry"] = e
            notes_placed.add(m["id"])
            search_entries.append({
                "id": m["id"], "type": "note", "stage_id": stage["id"],
                "branch_id": branch["id"] if branch else None,
                "grade_id": grade["id"], "subject_id": subject["id"],
                "title": e.get("title", ""), "search_keys": keys,
            })

    all_manifests = books + notes

    def build_stage(stage: dict, only_notes: bool) -> dict | None:
        out = {"id": stage["id"], "name": stage["name"], "name_en": stage["name_en"]}
        has_any = False

        def place(items: list[dict], branch_id: str | None, grade: dict, sid: str) -> tuple[list, list]:
            bk, nt = [], []
            for m in items:
                if m.get("_entry") is None:
                    continue
                if m["stage_id"] != stage["id"]:
                    continue
                if (m.get("branch_id") or None) != branch_id:
                    continue
                if m["grade_id"] != grade["id"] or m["subject_id"] != sid:
                    continue
                if not only_notes and m["id"] in book_by_id:
                    bk.append(m["_entry"])
                if m["id"] in note_by_id:
                    nt.append(m["_entry"])
            return bk, nt

        def build_grades(grades: list[dict], branch_id: str | None = None) -> list[dict]:
            out_grades = []
            for g in grades:
                out_subs = []
                for sid in g["subjects"]:
                    subject = next((s for s in tax["subjects"] if s["id"] == sid), None)
                    if subject is None:
                        continue
                    bk, nt = place(all_manifests, branch_id, g, sid)
                    if only_notes:
                        if not nt:
                            continue
                        out_subs.append({"id": sid, "name": subject["name"],
                                         "name_en": subject.get("name_en", ""), "notes": nt})
                    else:
                        if not bk:
                            continue
                        out_subs.append({"id": sid, "name": subject["name"],
                                         "name_en": subject.get("name_en", ""), "books": bk})
                if out_subs:
                    out_grades.append({"id": g["id"], "name": g["name"], "name_en": g["name_en"],
                                       "subjects": out_subs})
            return out_grades

        if stage.get("grades"):
            grades = build_grades(stage["grades"])
            if grades:
                out["grades"] = grades
                has_any = True
        if stage.get("branches"):
            branches = []
            for br in stage["branches"]:
                grades = build_grades(br["grades"], branch_id=br["id"])
                if grades:
                    branches.append({"id": br["id"], "name": br["name"],
                                     "name_en": br["name_en"], "grades": grades})
            if branches:
                out["branches"] = branches
                has_any = True
        return out if has_any else None

    all_manifests = books + notes

    def gen(only_notes: bool) -> list[dict]:
        stages = []
        for stage in tax["stages"]:
            out = build_stage(stage, only_notes)
            if out:
                stages.append(out)
        return stages

    return gen(False), gen(True), search_entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if build would change files")
    args = ap.parse_args()

    tax = load_taxonomy()
    books = read_manifests("books")
    notes = read_manifests("notes")
    books.sort(key=lambda m: (m["grade_id"], m["subject_id"], m.get("sort_order", 0), m["id"]))
    notes.sort(key=lambda m: (m["grade_id"], m["subject_id"], m.get("sort_order", 0), m["id"]))

    books_stages, notes_stages, search_entries = build_trees(tax, books, notes)

    placed = {e["id"] for e in search_entries}
    unplaced_books = [m["id"] for m in books if m["id"] not in placed]
    unplaced_notes = [m["id"] for m in notes if m["id"] not in placed]
    for uid in unplaced_books + unplaced_notes:
        print(f"WARNING: manifest not placed in taxonomy: {uid}")
    if unplaced_books or unplaced_notes:
        print("ERROR: content references an unknown taxonomy path — fix content/ before shipping")
        return 2

    max_book_date = max((m.get("updated_at", "") for m in books), default="")
    max_note_date = max((m.get("updated_at", "") for m in notes), default="")
    max_date = max(max_book_date, max_note_date) or "1970-01-01"

    curriculum = tax.get("curriculum_version", "")
    books_json = {"version": 0, "updated_at": max_book_date, "stages": books_stages}
    if curriculum:
        books_json["curriculum_version"] = curriculum
    notes_json = {"version": 0, "updated_at": max_note_date, "source": "iraqiteacher.com", "stages": notes_stages}

    search_index = {
        "version": 1, "updated_at": max_date,
        "entries": sorted(search_entries, key=lambda e: e["id"]),
    }

    artifacts = {
        "books.json": books_json,
        "notes.json": notes_json,
    }
    search_index_raw = json.dumps(search_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    state = load_json(STATE_FILE) if STATE_FILE.is_file() else None
    if state is None:
        state = {
            "catalogVersion": SEED_CATALOG_VERSION,
            "files": {n: {"version": v} for n, v in SEED_FILE_VERSIONS.items()},
        }
    prev_versions = {n: f.get("version", 0) for n, f in state["files"].items()}
    prev_shas = {n: f.get("sha256", "") for n, f in state["files"].items()}

    new_versions = dict(prev_versions)
    changed = []
    raw_bytes = {}
    for name, obj in artifacts.items():
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = sha256_bytes(raw + b"\n")
        raw_bytes[name] = raw
        if digest != prev_shas.get(name):
            new_versions[name] = prev_versions.get(name, 0) + 1
            changed.append(name)

    if changed:
        for name in changed:
            print(f"changed: catalog/{name} -> version {new_versions[name]}")
    else:
        print("no artifact changes")

    catalog_version = state["catalogVersion"] + (1 if changed else 0)

    manifest = {
        "catalogVersion": catalog_version,
        "updatedAt": f"{max_date}T00:00:00Z",
        "minimumAppVersion": 1,
        "files": [
            {
                "name": "books.json",
                "version": new_versions["books.json"],
                "sha256": sha256_bytes(raw_bytes["books.json"] + b"\n"),
                "sizeBytes": len(raw_bytes["books.json"]) + 1,
            },
            {
                "name": "notes.json",
                "version": new_versions["notes.json"],
                "sha256": sha256_bytes(raw_bytes["notes.json"] + b"\n"),
                "sizeBytes": len(raw_bytes["notes.json"]) + 1,
                "dependsOn": ["books.json"],
            },
        ],
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    new_state = {
        "catalogVersion": catalog_version,
        "files": {
            "books.json": {"version": new_versions["books.json"], "sha256": sha256_bytes(raw_bytes["books.json"] + b"\n")},
            "notes.json": {"version": new_versions["notes.json"], "sha256": sha256_bytes(raw_bytes["notes.json"] + b"\n")},
        },
    }

    if args.check:
        drift = []
        for name in ("books.json", "notes.json"):
            if (CATALOG_DIR / name).read_bytes() != raw_bytes[name] + b"\n":
                drift.append(name)
        if (CATALOG_DIR / "manifest.json").read_bytes() != manifest_raw + b"\n":
            drift.append("manifest.json")
        if (CATALOG_DIR / "search_index.json").read_bytes() != search_index_raw + b"\n":
            drift.append("search_index.json")
        if STATE_FILE.is_file() and load_json(STATE_FILE) != new_state:
            drift.append(".catalog_state.json")
        if drift:
            print("DRIFT: catalog is out of date — run: python tools/build.py")
            for d in drift:
                print(f"  stale: {d}")
            return 1
        print("OK: catalog is up to date")
        return 0

    for name, raw in raw_bytes.items():
        (CATALOG_DIR / name).write_bytes(raw + b"\n")
    (CATALOG_DIR / "search_index.json").write_bytes(search_index_raw + b"\n")
    (CATALOG_DIR / "manifest.json").write_bytes(manifest_raw + b"\n")

    dump_json(new_state, STATE_FILE)
    print(f"catalogVersion -> {catalog_version}")
    for name in ("books.json", "notes.json"):
        a = artifacts[name]
        print(f"  catalog/{name}: {len(raw_bytes[name]) + 1:,} B raw, sha256 {sha256_bytes(raw_bytes[name] + b'\n')[:16]}")
    print(f"  catalog/search_index.json: {len(search_index_raw) + 1:,} B, {len(search_entries)} entries")
    print(f"  catalog/manifest.json: {len(manifest_raw) + 1:,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())