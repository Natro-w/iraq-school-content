# Iraq School Content

Educational content repository for the Iraq School app (مدرسة العراق).

This repository serves the **book catalog** and **study notes** (ملازم) consumed by
the app through `catalog/manifest.json`. The app downloads `catalog/books.json` and
`catalog/notes.json` with SHA-256 verification (see the app's
`catalog_sync_service`/`catalog_downloader`).

## Layout

```
content/                  # Human-edited source (small per-item manifests)
├── taxonomy.json         # Stages, grades, branches, subjects (canonical order)
├── books/{id}/manifest.json    # One file per book
└── notes/{id}/manifest.json    # One file per ملزمة
catalog/                  # Machine-generated artifacts — DO NOT EDIT BY HAND
├── manifest.json         # versioned file list (fetched first by the app)
├── books.json            # Book catalog (app contract: BookCatalog.fromJson)
├── notes.json            # Notes catalog (same tree shape)
└── search_index.json     # Arabic-normalized search index (repo-only, future app versions)
thumbnails/               # {md5(pdf_url)}.jpg, content-addressed, served to the app
tools/                    # Python stdlib tooling (no dependencies)
├── ingest.py             # one-time migration from legacy data
├── build.py              # generate catalog/ from content/
├── validate.py           # strict content + artifact contract checks
├── check_links.py        # external PDF availability report (manual)
├── schema.py             # shared constants + loaders
└── normalize.py          # Arabic normalization for search keys
legacy/                   # pre-redesign files kept for reference
docs/architecture.md      # full design, benchmark tables, scaling plan
.github/workflows/content-ci.yml
```

## Workflows

### Add or update a book / note

1. Create or edit `content/books/{id}/manifest.json` (or `content/notes/{id}/manifest.json`).
   Use `tools/ingest.py`'s migration report or an existing manifest as a template.
   The `id` is stable and must never change once shipped.
2. Regenerate artifacts: `python tools/build.py`
3. Validate: `python tools/validate.py --strict`
4. Commit `content/`, the regenerated `catalog/`, and `.catalog_state.json`.

The build is **deterministic and incremental**: a one-file content change bumps only
the affected artifact version; `build.py --check` (run in CI) fails if the committed
catalog is stale. `validate.py --strict` enforces the app parser contract (e.g.
`authors` must be a list — the historical P1 crash cause), taxonomy integrity,
duplicate ids, and manifest↔state version equality.

### Release to users

The app detects updates by comparing `catalogVersion` (integer) and per-file
`version` integers in `catalog/manifest.json`; files are SHA-256 verified and
written as `books.json`/`notes.json` on device. Bumping content in `content/` and
running `python tools/build.py` is all that is needed — the new manifest carries
the bumped versions.

## Taxonomy

| Stage | Arabic | Grades | Branches |
|-------|--------|--------|----------|
| primary | المرحلة الابتدائية | grade-1..6 | — |
| intermediate | المرحلة المتوسطة | grade-1..3 | — |
| preparatory | المرحلة الإعدادية | grade-4..6 | scientific, literary, vocational |

Notes and books share this taxonomy; notes use the same canonical grade ids.
Subjects (17) are shared and defined in `content/taxonomy.json`.

## Current content

- 135 books, 574 ملازم (709 catalog entries), 105 cover thumbnails matched to
  current PDFs (489 total, incl. legacy entries so older installed caches keep
  working), 6 known books without remote thumbnails (app falls back to local
  generation).

## Development

Requires Python 3.10+ (stdlib only). Commands:

```
python tools/validate.py --strict   # full content + artifact check
python tools/build.py --check       # drift check (CI)
python tools/build.py               # regenerate artifacts
python tools/check_links.py         # report dead/moved PDF URLs (network heavy)
```

## License / Attribution

All content belongs to the Iraqi Ministry of Education and respective authors;
metadata is maintained for the Iraq School app only.