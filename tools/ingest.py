"""One-time migration: legacy JSON catalogs -> content/ manifests + taxonomy.

Idempotent and reversible (output is additive; legacy files untouched).
Run: python tools/ingest.py [--legacy-dir legacy|.]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import (  # noqa: E402
    BOOK_ID_RE, MIGRATION_REPORT, NOTE_ID_RE, SCHEMA_VERSION, TAXONOMY_FILE,
    BOOKS_DIR, NOTES_DIR, REPO_ROOT, load_json, dump_json,
)

MIGRATION_DATE = date.today().isoformat()

# canonical grade mapping for notes (verified against note titles)
NOTES_GRADE_MAP = {
    ("primary", "grade-primary-0"): "grade-4",
    ("primary", "grade-primary-1"): "grade-5",
    ("primary", "grade-primary-2"): "grade-6",
    ("intermediate", "grade-intermediate-0"): "grade-1",
    ("intermediate", "grade-intermediate-1"): "grade-2",
    ("intermediate", "grade-intermediate-2"): "grade-3",
    ("preparatory", "scientific", "grade-preparatory-0"): "grade-4",
    ("preparatory", "scientific", "grade-preparatory-1"): "grade-5",
    ("preparatory", "scientific", "grade-preparatory-2"): "grade-6",
    ("preparatory", "literary", "grade-preparatory_literary-0"): "grade-5",
    ("preparatory", "literary", "grade-preparatory_literary-1"): "grade-6",
    ("preparatory", "vocational", "grade-preparatory_vocational-0"): "grade-6",
}

CDN = "https://h1.iraqiteacher.com"


def absolutize(url: str) -> str:
    if url.startswith("http"):
        return url
    return CDN + ("/" + url.lstrip("/") if url else url)


def norm_authors(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    out = []
    for a in v or []:
        a = str(a).strip()
        if a:
            out.append(a)
    return out


def build_taxonomy(books_json: dict, notes_json: dict, subjects: list[dict]) -> dict:
    """Canonical tree from the books catalog, extended with the notes' vocational branch."""
    stages = []
    subjects_by_id = {s["id"]: s for s in subjects}

    def subject_node(sid: str) -> dict:
        s = subjects_by_id.get(sid)
        if s is None:
            s = {"id": sid, "name": sid, "name_en": sid}
        return {"id": s["id"], "name": s["name"], "name_en": s.get("name_en", "")}

    for stage in books_json["stages"]:
        out_stage = {"id": stage["id"], "name": stage["name"], "name_en": stage["name_en"]}
        if stage.get("grades"):
            grades = []
            for g in stage["grades"]:
                grades.append({
                    "id": g["id"], "name": g["name"], "name_en": g["name_en"],
                    "subjects": [sub["id"] for sub in g["subjects"]],
                })
            out_stage["grades"] = grades
        if stage.get("branches"):
            branches = []
            for br in stage["branches"]:
                grades = []
                for g in br["grades"]:
                    grades.append({
                        "id": g["id"], "name": g["name"], "name_en": g["name_en"],
                        "subjects": [sub["id"] for sub in g["subjects"]],
                    })
                branches.append({"id": br["id"], "name": br["name"], "name_en": br["name_en"], "grades": grades})
            out_stage["branches"] = branches
        stages.append(out_stage)

    # Extend preparatory with vocational branch from notes (books have none).
    prep = next(s for s in stages if s["id"] == "preparatory")
    notes_prep = next(s for s in notes_json["stages"] if s["id"] == "preparatory")
    if "branches" not in prep:
        prep["branches"] = []
    existing = {br["id"] for br in prep["branches"]}
    for br in notes_prep["branches"]:
        if br["id"] not in existing:
            grades = []
            for g in br["grades"]:
                grades.append({
                    "id": NOTES_GRADE_MAP.get(("preparatory", br["id"], g["id"]), g["id"]),
                    "name": g["name"], "name_en": g["name_en"],
                    "subjects": [sub["id"] for sub in g["subjects"]],
                })
            prep["branches"].append({
                "id": br["id"], "name": br["name"], "name_en": br["name_en"], "grades": grades,
            })

    # Merge notes-only subjects into grade subject order (append, keep notes order).
    for stage in notes_json["stages"]:
        for s in stages:
            if s["id"] != stage["id"]:
                continue
            groups = (s.get("grades") or []) + [g for br in (s.get("branches") or []) for g in br["grades"]]
            notes_groups = (stage.get("grades") or []) + [g for br in (stage.get("branches") or []) for g in br["grades"]]
            for ng in notes_groups:
                key = ("preparatory", ng.get("branch_id", ""), ng["id"])
                canonical = None
                if stage["id"] == "preparatory" and ng.get("branch_id"):
                    canonical = NOTES_GRADE_MAP.get(("preparatory", ng["branch_id"], ng["id"]))
                else:
                    canonical = NOTES_GRADE_MAP.get((stage["id"], ng["id"]), ng["id"])
                if canonical is None:
                    canonical = ng["id"]
                target = None
                for g in groups:
                    if g["id"] == canonical:
                        target = g
                        break
                if target is None:
                    continue
                for sub in ng["subjects"]:
                    sid = sub if isinstance(sub, str) else sub.get("id")
                    if sid and sid not in target["subjects"]:
                        target["subjects"].append(sid)

    tax = {
        "schema_version": SCHEMA_VERSION,
        "curriculum_version": books_json.get("curriculum_version", ""),
        "stages": stages,
        "subjects": [subject_node(s["id"]) for s in subjects],
    }
    return tax


def walk_tree(j: dict):
    """Yield (stage, branch|None, grade, subject, items) in legacy order."""
    for stage in j["stages"]:
        for grade in stage.get("grades") or []:
            for subject in grade["subjects"]:
                items = subject.get("books") or subject.get("notes") or []
                if items:
                    yield stage, None, grade, subject, items
        for branch in stage.get("branches") or []:
            for grade in branch["grades"]:
                for subject in grade["subjects"]:
                    items = subject.get("books") or subject.get("notes") or []
                    if items:
                        yield stage, branch, grade, subject, items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-dir", default=str(REPO_ROOT))
    args = ap.parse_args()
    legacy = Path(args.legacy_dir)

    books_json = load_json(legacy / "books.json")
    notes_json = load_json(legacy / "notes.json")
    subjects = load_json(legacy / "subjects.json")

    tax = build_taxonomy(books_json, notes_json, subjects)
    dump_json(tax, TAXONOMY_FILE)
    print(f"taxonomy: {TAXONOMY_FILE} ({len(tax['stages'])} stages, {len(tax['subjects'])} subjects)")

    report = {
        "migrated_at": MIGRATION_DATE,
        "sources": ["books.json", "notes.json", "subjects.json"],
        "deduplicated_ids": [],
        "url_fixes": [],
        "grade_mappings": {},
        "unknown_subjects": [],
        "books_written": 0,
        "notes_written": 0,
        "notes_skipped_missing_grade": [],
    }

    def book_manifest(stage, branch, grade, subject, b, order):
        bid = b["id"]
        if not BOOK_ID_RE.match(bid):
            report.setdefault("bad_book_ids", []).append(bid)
        pdf = absolutize(b.get("pdf_url", ""))
        if b.get("pdf_url") != pdf:
            report["url_fixes"].append({"id": bid, "from": b.get("pdf_url"), "to": pdf})
        m = {
            "schema_version": SCHEMA_VERSION,
            "id": bid,
            "stage_id": stage["id"],
            "branch_id": branch["id"] if branch else None,
            "grade_id": grade["id"],
            "subject_id": subject["id"],
            "sort_order": order,
            "title": b.get("title", ""),
            "title_en": b.get("title_en", ""),
            "part": b.get("part"),
            "parts_total": b.get("parts_total"),
            "description": b.get("description", ""),
            "authors": norm_authors(b.get("authors")),
            "publisher": b.get("publisher", ""),
            "year": b.get("year", 0),
            "edition": b.get("edition", ""),
            "isbn": b.get("isbn", ""),
            "pages": b.get("pages", 0) or None,
            "size_bytes": b.get("size_bytes", 0) or None,
            "cover_url": b.get("cover_url", ""),
            "pdf_url": pdf,
            "metadata_url": b.get("metadata_url", ""),
            "curriculum_version": b.get("curriculum_version", ""),
            "status": b.get("status", "active"),
            "source": "", "source_url": "", "license": "",
            "added_at": MIGRATION_DATE, "updated_at": MIGRATION_DATE,
            "migrated_from": "legacy books.json",
        }
        dump_json(m, BOOKS_DIR / bid / "manifest.json")
        report["books_written"] += 1

    def note_manifest(stage, branch, grade, subject, n, order):
        nid = n["id"]
        if not NOTE_ID_RE.match(nid):
            report.setdefault("bad_note_ids", []).append(nid)
        key = (stage["id"], branch["id"] if branch else None, grade["id"])
        if branch:
            canonical = NOTES_GRADE_MAP.get((stage["id"], branch["id"], grade["id"]))
        else:
            canonical = NOTES_GRADE_MAP.get((stage["id"], grade["id"]))
        if canonical is None:
            report["notes_skipped_missing_grade"].append(nid)
            return
        report["grade_mappings"].setdefault(grade["id"], canonical)
        m = {
            "schema_version": SCHEMA_VERSION,
            "id": nid,
            "stage_id": stage["id"],
            "branch_id": branch["id"] if branch else None,
            "grade_id": canonical,
            "subject_id": subject["id"],
            "sort_order": order,
            "title": n.get("title", ""),
            "author": n.get("author") or "",
            "pdf_url": absolutize(n.get("pdf_url", "")),
            "pages": n.get("pages"),
            "source": n.get("source", ""),
            "source_url": n.get("source_url", ""),
            "license": "",
            "status": "active",
            "added_at": MIGRATION_DATE, "updated_at": MIGRATION_DATE,
            "migrated_from": "legacy notes.json",
        }
        dump_json(m, NOTES_DIR / nid / "manifest.json")
        report["notes_written"] += 1

    seen_books: set[str] = set()
    for stage, branch, grade, subject, items in walk_tree(books_json):
        order = 0
        for b in items:
            if b["id"] in seen_books:
                report["deduplicated_ids"].append(b["id"])
                continue
            seen_books.add(b["id"])
            book_manifest(stage, branch, grade, subject, b, order)
            order += 1

    seen_notes: set[str] = set()
    for stage, branch, grade, subject, items in walk_tree(notes_json):
        order = 0
        for n in items:
            if n["id"] in seen_notes:
                report["deduplicated_ids"].append(n["id"])
                continue
            seen_notes.add(n["id"])
            note_manifest(stage, branch, grade, subject, n, order)
            order += 1

    MIGRATION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    dump_json(report, MIGRATION_REPORT)
    print(json.dumps({k: v for k, v in report.items() if k not in ("grade_mappings",)}, ensure_ascii=False, indent=1))
    print(f"books: {report['books_written']} (legacy had {len(seen_books)} unique ids)")
    print(f"notes: {report['notes_written']}")
    print(f"report: {MIGRATION_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())