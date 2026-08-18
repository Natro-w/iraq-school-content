"""Validate content/ manifests and generated catalog/ artifacts.

Exit codes: 0 = clean, 1 = errors, 2 = warnings-only (with --strict).

Run: python tools/validate.py [--strict] [--skip-catalog]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import (  # noqa: E402
    BOOK_ID_RE, CATALOG_DIR, NOTE_ID_RE, STATE_FILE, load_json,
    read_manifests, load_taxonomy, find_taxonomy_path, validate_id_format,
    ALLOWED_STATUS,
)

URL_RE = re.compile(r"^https://[a-zA-Z0-9.-]+\.[a-z]{2,}")

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
BOOKS_DIR_PATH = CONTENT_DIR / "books"
NOTES_DIR_PATH = CONTENT_DIR / "notes"


class Report:
    def __init__(self, strict: bool):
        self.strict = strict
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def info(self, msg: str):
        self.infos.append(msg)

    @property
    def failed(self) -> bool:
        return bool(self.errors) or (self.strict and bool(self.warnings))


def check_content(r: Report) -> None:
    tax = load_taxonomy()
    stage_ids = {s["id"] for s in tax["stages"]}
    grade_ids = set()
    branch_ids = set()
    for s in tax["stages"]:
        for g in s.get("grades") or []:
            grade_ids.add(g["id"])
        for br in s.get("branches") or []:
            branch_ids.add(br["id"])
            for g in br["grades"]:
                grade_ids.add(g["id"])
    subject_ids = {s["id"] for s in tax["subjects"]}

    for s in tax["stages"]:
        groups = list(s.get("grades") or [])
        for br in s.get("branches") or []:
            groups.extend(br["grades"])
        for g in groups:
            for sub in g["subjects"]:
                if not isinstance(sub, str):
                    r.error(f"taxonomy: non-string subject entry in {s['id']}/{g['id']}: {type(sub).__name__} (run tools/ingest.py to regenerate)")

    seen_ids: set[str] = set()
    seen_urls: dict[str, list[str]] = {}
    books = read_manifests("books")
    notes = read_manifests("notes")

    for kind, manifests in (("books", books), ("notes", notes)):
        for m in manifests:
            mid = m.get("id", "")
            if not validate_id_format(kind, mid):
                r.error(f"{kind}: invalid id format: {mid!r}")
            if mid in seen_ids:
                r.error(f"{kind}: duplicate id: {mid}")
            seen_ids.add(mid)

            path = find_taxonomy_path(tax, m)
            if path is None:
                r.error(f"{kind} {mid}: unknown taxonomy path "
                        f"(stage={m.get('stage_id')}, branch={m.get('branch_id')}, "
                        f"grade={m.get('grade_id')}, subject={m.get('subject_id')})")
            else:
                stage, branch, grade, subject = path
                if stage["id"] not in stage_ids:
                    r.error(f"{kind} {mid}: bad stage_id {stage['id']}")
                if m.get("branch_id") and m["branch_id"] not in branch_ids:
                    r.error(f"{kind} {mid}: bad branch_id {m['branch_id']}")
                if grade["id"] not in grade_ids:
                    r.error(f"{kind} {mid}: bad grade_id {grade['id']}")
                if subject["id"] not in subject_ids:
                    r.error(f"{kind} {mid}: bad subject_id {subject['id']}")

            url = m.get("pdf_url", "")
            if not url:
                r.error(f"{kind} {mid}: missing pdf_url")
            elif not URL_RE.match(url):
                r.error(f"{kind} {mid}: pdf_url not absolute https: {url}")
            else:
                seen_urls.setdefault(url, []).append(f"{kind}:{mid}")

            if kind == "books":
                for f in ("title", "title_en"):
                    if not m.get(f):
                        r.error(f"book {mid}: missing {f}")
                if not isinstance(m.get("authors"), list) or not m["authors"]:
                    r.error(f"book {mid}: authors must be a non-empty list")
                if m.get("status") not in ALLOWED_STATUS:
                    r.error(f"book {mid}: bad status {m.get('status')!r}")
                if m.get("part") is None and m.get("parts_total") is not None:
                    r.error(f"book {mid}: parts_total without part")
            else:
                if not m.get("title"):
                    r.error(f"note {mid}: missing title")
                if m.get("status") not in ALLOWED_STATUS:
                    r.error(f"note {mid}: bad status {m.get('status')!r}")

            dir_path = BOOKS_DIR_PATH if kind == "books" else NOTES_DIR_PATH
            if not (dir_path / mid / "manifest.json").is_file():
                r.error(f"{kind}: manifest path mismatch for {mid}")

    for url, ids in seen_urls.items():
        if len(ids) > 1:
            r.info(f"duplicate pdf_url across {len(ids)} items: {url} ({', '.join(ids)})")

    if not books:
        r.error("no book manifests found")
    if not notes:
        r.error("no note manifests found")


def check_catalog(r: Report) -> None:
    """App-parser compatibility regression check (the P1 crash guard)."""
    if not (CATALOG_DIR / "manifest.json").is_file():
        r.error("catalog/manifest.json missing — run tools/build.py")
        return

    manifest = load_json(CATALOG_DIR / "manifest.json")
    files = {f["name"]: f for f in manifest["files"]}
    for name in ("books.json", "notes.json"):
        entry = files.get(name)
        if entry is None:
            r.error(f"manifest missing entry {name}")
            continue
        p = CATALOG_DIR / name
        if not p.is_file():
            r.error(f"catalog/{name} missing")
            continue
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            r.error(f"catalog/{name} sha256 mismatch vs manifest")

    state = load_json(STATE_FILE) if STATE_FILE.is_file() else {}
    for name in ("books.json", "notes.json"):
        j = load_json(CATALOG_DIR / name)

        def walk(obj):
            yield obj
            for s in obj.get("stages") or []:
                for g in s.get("grades") or []:
                    yield g
                    for sub in g.get("subjects") or []:
                        yield sub
                        for bk in sub.get("books") or []:
                            yield bk
                        for nt in sub.get("notes") or []:
                            yield nt
                for br in s.get("branches") or []:
                    for g in br.get("grades") or []:
                        yield g
                        for sub in g.get("subjects") or []:
                            yield sub
                            for bk in sub.get("books") or []:
                                yield bk
                            for nt in sub.get("notes") or []:
                                yield nt

        ids: set[str] = set()
        for node in walk(j):
            if "id" in node and "title" in node:
                if node["id"] in ids:
                    r.error(f"catalog/{name}: duplicate id {node['id']}")
                ids.add(node["id"])
                if not node.get("title"):
                    r.error(f"catalog/{name}: empty title for {node['id']}")
                if "authors" in node and not isinstance(node["authors"], list):
                    r.error(f"catalog/{name}: authors not a list for {node['id']}  <-- app parser crash (P1)")
                if name == "books.json" and not isinstance(node.get("title_en"), str):
                    r.error(f"catalog/{name}: missing title_en for {node['id']}")
                if node.get("pdf_url") and not node["pdf_url"].startswith("https://"):
                    r.error(f"catalog/{name}: non-https pdf_url for {node['id']}")
        if name == "books.json" and "stages" not in j:
            r.error("catalog/books.json missing top-level stages")
        if name == "notes.json" and "stages" not in j:
            r.error("catalog/notes.json missing top-level stages")

        ver = state.get("files", {}).get(name, {}).get("version", 0)
        manifest_ver = files.get(name, {}).get("version", 0)
        if manifest_ver != ver:
            r.error(f"catalog/manifest.json: {name} version {manifest_ver} != state version {ver} (run tools/build.py)")

    if manifest.get("minimumAppVersion", 0) < 1:
        r.error("manifest minimumAppVersion must be >= 1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="warnings fail the run")
    ap.add_argument("--skip-catalog", action="store_true")
    args = ap.parse_args()

    r = Report(args.strict)
    check_content(r)
    if not args.skip_catalog:
        check_catalog(r)

    for w in r.warnings:
        print(f"WARN: {w}")
    for e in r.errors:
        print(f"ERROR: {e}")
    for i in r.infos:
        print(f"INFO: {i}")
    print(f"content+artifacts: {len(r.errors)} errors, {len(r.warnings)} warnings, {len(r.infos)} infos")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())