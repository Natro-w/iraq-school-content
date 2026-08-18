# Iraq School Content — Architecture Assessment & Redesign

Status: assessment complete, design v1. Date: 2026-08-19. Repo: `Natro-w/iraq-school-content`.

---

## 1. Current problems (verified, measured)

### P1 — PRODUCTION-BREAKING: served catalog crashes the app parser
`catalog/books.json` (the file the production manifest serves to every device) has
69 of 143 books with `authors` as a **string**; the app's `BookInfo.fromJson`
(`lib/features/books/domain/models/books_catalog.dart:192`) does `(json['authors'] as List?)`.
Verified with the app's real parser via `dart run`:

```
CRASH: catalog/books.json -> _TypeError: type 'String' is not a subtype of type 'List<dynamic>?' in type cast
OK:    root books.json (audit-repaired) -> 135 books
```

Effect: manifest-based sync (the only path new installs use) parses `catalog/books.json`,
crashes, falls back to cache. Existing installs keep stale cache forever; **new installs get
no catalog**. `catalog/notes.json` parses fine. Root `books.json` (audit version, `390f9b2`)
is safe but **is not served by the manifest flow**.

### P2 — Two divergent catalogs, three vocabularies
- Root `books.json` (167 KB) vs `catalog/books.json` (405 KB): same version/updated_at/143
  entries, 135 unique ids, 61 books with different content (`authors` type difference;
  catalog also carries richer fields). Root was repaired by the audit PR (`390f9b2`),
  `catalog/` was generated earlier (`9a40e50`) and never regenerated — the two now drift.
- Grade id vocabularies differ: books use `grade-1..6` / `grade-4..6`; notes use
  `grade-primary-0..2`, `grade-preparatory_literary-0..1`, etc. Same stage ids
  (`primary/intermediate/preparatory`), inconsistent grade ids. Subjects are consistent
  (17 ids, `subjects.json` == books.json).

### P3 — Duplicate ids
8 ids appear twice in BOTH catalogs (`prep-grade-6-arabic-120/121/128/129`,
`prep-grade-6-english-122/123`, `prep-grade-6-islamic-130`, `prep-grade-6-math-127`) with
identical content — the tree has 143 entries, 135 unique ids. App `CatalogIndex` silently
dedupes by last-write-wins.

### P4 — Empty/placeholder fields
135/143 books have `pages:0`, `size_bytes:0`, `cover_url:""`, `metadata_url:""`. The
rich `books/primary/grade-1/math/metadata.json` example is orphaned (no book references it).
Reader features that depend on page counts fall back to defaults.

### P5 — Broken relative PDF URLs
6 books (`prep-grade-6-*`) have relative `pdf_url` (`/uploaded/2025-11/...`). App fallback
chain (`reader_repository.dart:107-132`) tries `raw.githubusercontent` then
`iraqiteacher.com` then `iraqiteacher.com/pdfs` — verified the second candidate resolves
(`206, %PDF, 17 MB`), but the URL is wrong by design and thumbnails for these books 404.

### P6 — Thumbnails missing on main
489 thumbnails (`thumbnails/{md5(pdf_url)}.jpg`, generated in `488a0e1`) exist ONLY on the
`master` branch, which is not an ancestor of `main`. The app fetches
`gitHubContentBaseUrl/thumbnails/{md5(pdf_url)}.jpg` (`book_thumbnail.dart:47`).
137 of the 143 current `pdf_url`s match an existing thumbnail; all 404 today on `main`.
The 6 relative-URL books would still miss (hash of the relative string).

### P7 — No tooling, no CI, no validation
Single-file hand-edited JSON; manifest hashes had to be hand-maintained (commits
`b4d14c8`–`b7c6814` are hash-fix commits). No schema validation, no link checking,
no drift detection, no duplicate detection. One `books/` example directory contradicts
the README (no PDFs/cover.png anywhere).

### P8 — Monolithic generated files (scaling risk)
`catalog/books.json` 405 KB raw (14.3 KB gzip on the wire) / `catalog/notes.json`
753 KB raw (34.8 KB gzip). Fine today (decode 2.3 ms / 4.9 ms locally), but the
manifest contract (v1) re-downloads whole files per change. 10k/50k/100k books →
~1–11 MB gzip full downloads on first install and on every bumped file.

### P9 — Documentation mismatch
README documents a `books/{stage}/{grade}/{subject}/{metadata.json,book.pdf,cover.png}`
structure that does not exist in the repo (no PDFs/cover.png anywhere).

### P10 — No license/attribution/removal metadata
`notes.json` has `source`/`source_url`; books have none. No per-item license, no
legal-removal workflow, no audit trail.

## 2. Baseline benchmarks (before)

Measured from this network (raw.githubusercontent.com, `main` branch):

| artifact | raw | gzip wire | fetch | decode (local) |
|---|---|---|---|---|
| `catalog/manifest.json` | 505 B | 290 B | 0.54 s | — |
| `catalog/books.json` | 405,066 B | 14,317 B | 0.82 s | 2.3 ms |
| `catalog/notes.json` | 753,493 B | 34,804 B | 0.62 s | 4.9 ms |

Also: root `books.json` 167,321 B; root `notes.json` 327,854 B; `subjects.json` 1,754 B.

### After (final artifacts, same network + local decode)

| artifact | raw | gzip wire | fetch | decode (local) |
|---|---|---|---|---|
| `catalog/manifest.json` | 372 B | 265 B | 2.3–5.0 s (latency-bound) | 0.03 ms |
| `catalog/books.json` | 76,319 B | 7,428 B | latency-bound | 0.83 ms |
| `catalog/notes.json` | 195,092 B | 25,867 B | latency-bound | 1.80 ms |

Net result: books wire size **−48%** (14,317 → 7,428 B gzip), notes **−26%**
(34,804 → 25,867 B gzip); decode ~2.8× faster. Fetch on raw.githubusercontent is
dominated by round-trip latency (~2–5 s from this region) rather than size; the
size cut matters more for slow 2G/3G networks in the field.

## 3. Architecture chosen — hybrid source-of-truth → generated artifacts

```
iraq-school-content/
├── content/                          # HUMAN-EDITABLE SOURCE OF TRUTH (never served to app)
│   ├── taxonomy.json                 # canonical stages/branches/grades/subjects (single vocabulary)
│   ├── books/<book_id>/manifest.json # 135 files, one per book (rich metadata, strict schema)
│   ├── notes/<note_id>/manifest.json # 574 files, one per ملزمة
│   └── README.md                     # how to add content (workflow for humans)
├── catalog/                          # MACHINE-GENERATED ARTIFACTS (app-consumed, never hand-edited)
│   ├── manifest.json                 # v5 — same byte-compatible schema, per-file versions
│   ├── books.json                    # app-schema catalog (fixed authors, deduped, absolute URLs)
│   ├── notes.json                    # app-schema notes in canonical hierarchy
│   └── search_index.json             # Arabic-normalized index for future app versions
├── thumbnails/<md5>.jpg              # restored 489 from master (app-compatible naming)
├── legacy/                           # original books.json/notes.json/subjects.json (non-destructive)
├── tools/                            # Python 3 stdlib-only tooling
├── docs/                             # architecture + migration docs
├── .github/workflows/content-ci.yml  # validate + build + drift check
└── README.md                         # rewritten to match reality
```

### Why JSON for generated artifacts (format decision)
The shipped app contract (`minimumAppVersion=1`) is fixed JSON: manifest schema
(`catalog_manifest.dart`), `version`/`updated_at`/`stages` top-level, per-book keys,
byte-verified sha256, file names `manifest.json`/`books.json`/`notes.json`, atomic
staging writes. SQLite/JSONL would require an app rewrite and lose the 8 KB gzip
delta sync. JSON is kept for artifacts; the **source of truth becomes many small
per-item JSON manifests** (human-reviewable diffs, incremental indexing, easy PR
review) — JSONL/CSV buy nothing here and lose validation ergonomics.

### Stable IDs
Existing ids are preserved and become immutable (`pri-grade-1-islamic-1`,
`note-1063`, canonical `grade-4`, `subject-math`). IDs are never derived from
filenames; the `<book_id>/manifest.json` path convention is an ergonomic mapping
that `validate.py` enforces (path == id, id format enforced).

### Canonical hierarchy (single vocabulary, fixes P2)
```
primary       (المرحلة الابتدائية)      grades grade-1..grade-6
intermediate  (المرحلة المتوسطة)        grades grade-1..grade-3
preparatory   (المرحلة الإعدادية)       branches scientific|literary|vocational × grade-4..grade-6
```
Notes remapped during migration: `grade-primary-0→grade-4` … `-2→grade-6`,
`grade-intermediate-0→grade-1` …, `grade-preparatory-*→grade-4..6`
(verified against note titles: "للصف الرابع الابتدائي" etc.).

### Content-addressing & incremental indexing (fixes P7/P8)
- Every generated file carries a sha256 in the manifest (already the app contract).
- `build.py` is **deterministic** (sorted keys, fixed separators, stable timestamps
  only from content state) and **incremental**: content manifest changed → rebuilds
  only that entry; per-file `version` bumps only when that file's bytes change;
  `catalogVersion` bumps monotonically on any change (app's `isNewerThan` is `>`).
- Duplicate detection by `pdf_url` AND (when fetched) content sha256 of the PDF bytes.
- Scaling path (documented, additive, non-breaking): per-stage shard files
  (`books-primary.json`, `notes-preparatory.json`, …) added to the manifest with
  `dependsOn`, gated by `minimumAppVersion: 2`. App v1 downloads only
  `books.json`+`notes.json` (its parser reads exactly those names). No code path
  breaks; the composite files keep the v1 contract until v2 ships.

### Arabic search normalization (originals preserved)
`tools/normalize.py`: strip diacritics, unify أ/إ/آ→ا, ة→ه, ى→ي, remove tatweel,
collapse whitespace. Generated into per-book `search_keys` (additive keys the app
ignores) + `catalog/search_index.json` for future app versions. Original
`title`/`title_en`/`description` are never modified.

### GitHub strategy
Normal git (no LFS): repo stays ~8 MB total (text manifests + 489 small JPGs).
PDF binaries remain on the CDN (iraqiteacher.com/h1) — LFS would add cost and
hosting without benefit; the CDN already serves 149,08,272-byte files with range
support. `legacy/` preserves the old files; destructive changes are commits only
(reversible via git history).

### Security
- Ingest treats every external file as untrusted: `%PDF`/`%E2` magic check, HTTPS-only,
  host allowlist, size/time limits, never stored in repo.
- Content manifests are data-only (no scripts/HTML); the app renders text only.
- CI runs validation on every PR; release workflow regenerates + verifies hashes.

## 4. Migration plan (reversible, id-preserving)
1. `tools/ingest.py` reads legacy `books.json` + `notes.json`, normalizes
   (authors→list, 6 relative URLs→absolute `https://h1.iraqiteacher.com/uploaded/...`
   verified 206/PDF, dedupe 8 duplicated ids, notes grade remap) and writes
   `content/books/*/manifest.json` + `content/notes/*/manifest.json` with a
   `migrated_from` audit field.
2. `tools/build.py` generates `catalog/` v5 + `search_index.json`.
3. Thumbnails restored from `master` (`git checkout remotes/origin/master -- thumbnails/`).
4. Old root files moved to `legacy/` (kept, not deleted).
5. CI + docs + README.
6. Benchmark after, final report.

## 5. Remaining risks
- `catalogVersion`/file `version` bumps must keep the app's `>` comparison working
  (v5 > v4; books.json version 3 > 2; notes.json version 2 > 1).
- The 6 prep-grade-6 books previously 404'd thumbnails; after URL fix they still lack
  thumbnails (no master render) — flagged, not blocking (app falls back to local
  generation).
- `legacy/` files double repo size (~500 KB) — acceptable; delete later via separate
  decision.
- Notes grade mapping is title-derived; `ingest.py` logs every mapping for review.