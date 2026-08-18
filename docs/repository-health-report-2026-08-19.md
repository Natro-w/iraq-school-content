# Repository Health Report — iraq-school-content

**Date**: 2026-08-19
**Repo**: https://github.com/Natro-w/iraq-school-content (public)
**Scope**: full forensic audit — structure, history, content integrity, security, CI, performance, future scale
**Method**: read-only audit + evidence-based cleanup (no blind deletion; every deletion recoverable from git history)

---

## 1. Executive Summary

The repository is healthy and small (≈30 MB incl. `.git`), far below GitHub's practical limits. One **production bug was found and fixed**: 19 notes (of 574) were silently missing from the app-facing `catalog/notes.json` because `ingest.py` polluted `content/taxonomy.json` grade subjects with embedded note dicts, and `find_taxonomy_path` never verified grade-subject membership. Catalog rebuilt (notes v6, catalogVersion 9); all 574 notes now present and CI now guards against recurrence.

No secrets, no large blobs, no orphan files, no untracked strays. GitHub repo settings are mostly unconfigured (no branch protection, no topics, no releases) — recommendations below.

---

## 2. Research (GitHub best practices consulted)

| Topic | Guidance | Applied |
|---|---|---|
| File size limits | Warning at 50 MiB, hard block at 100 MiB (regular Git); 25 MiB via browser upload | Largest blob = 753 KB (`catalog/notes.json`). No risk. |
| Repo size | Recommended < 1 GB; < 5 GB strongly recommended | Working tree 16.2 MB, `.git` 14.7 MB. No risk. |
| LFS | For files beyond limits; adds complexity | **Not warranted** — JPGs already compressed, nothing near limits. |
| Releases | Preferred channel for large binaries | Recommended: publish APK via GitHub Releases (app already fetches APK from releases). |
| Actions security | Pin actions to full commit SHA; least-privilege `GITHUB_TOKEN`; Dependabot | **Applied in this audit** (see §9). |

---

## 3. Repository Structure & Inventory

```
~30 MB total (working tree 16.2 MB, .git 14.7 MB; 1,222 tracked files)
├── content/           711 files  books (135) + notes (574) manifests + taxonomy.json  [production source]
├── catalog/             4 files  generated artifacts: books.json, notes.json, search_index.json, manifest.json
├── thumbnails/        488 files  pre-generated JPG covers (md5(pdf_url).jpg) — app cache seed
├── legacy/              4 files  pre-migration JSON catalogs + migration report  [reference only]
├── tools/              10 files  build/validate/ingest/audit/check_links + helpers
├── docs/                2 files  architecture + redesign report
├── .github/             2 files  CI workflow + dependabot
└── root                 ~6 files  README, .gitignore, .gitattributes, .catalog_state.json, .env
```

Max dir width 2, max depth 5. No tags. One branch (`main`) after cleanup.

---

## 4. Findings & Fixes (this audit)

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | **19 notes missing from catalog tree** (555/574) — root cause: taxonomy pollution + lax `find_taxonomy_path` | **P1 production** | **Fixed** — see §5 |
| 2 | Corrupt thumbnail `a2ca0ef9…jpg` (30 KB all-zero header) referenced by note-1056 | Medium | Deleted (recoverable from git) |
| 3 | `legacy/example_books_tree` — 1 unreferenced example file from old structure | Low | Deleted (recoverable from git) |
| 4 | Branches `master` + `audit/curriculum-json-repair` — fully redundant (master had zero unique thumbnails; audit branch verified ancestor of main) | Low | Deleted via `git push origin --delete` (all commits live on main) |
| 5 | CI used mutable action refs (`@v4`, `@v5`), no dependabot, no concurrency | Medium | Pinned to SHAs, added dependabot + concurrency, added audit checks to CI |
| 6 | No `.gitattributes` — CRLF/LF normalization unmanaged | Low | Added (LF everywhere; jpg/png/pdf binary) |
| 7 | `note-550` title double whitespace | Low | Fixed |
| 8 | 12 literary-branch notes tagged `subject=social` but actually geography/history/economics | Medium | Fixed manifests per titles |

### Deliberately NOT deleted (conservative)
- `thumbnails/` files not matching current books (384 files) — served to old installs' caches; harmless 14 MB.
- 197 manifests without local thumbs — app falls back to network URL; generation is out of scope.
- 8 duplicate-thumbnail groups (23 files, ~296 KB) — different md5 names ⇒ different pdf_urls mapping to identical images = duplicate-book evidence, NOT repo junk. Report only.
- 17 shared `pdf_url` groups (books) — pre-existing content facts (e.g. French book shared across grades 1–3), INFO level.
- `legacy/*.json` + `migration_report.json` — reproducibility of the migration.
- `.env` — required asset for tooling.

---

## 5. The 19-Missing-Notes Bug (root cause + fix)

**Symptom**: `catalog/notes.json` contained 555 of 574 note manifests. Search index had all 709 entries (all manifests "placed" via search), so the gap was invisible to the build's unplaced-check.

**Root cause chain**:
1. `ingest.py` merged legacy notes-grade subjects by appending raw dicts (`sub not in target["subjects"]`) instead of `sub["id"]` → `content/taxonomy.json` grade `subjects` arrays contained **mixed strings and dicts with embedded notes**.
2. `build.py` tree placement iterates only string entries (`for sid in g["subjects"]`); dict entries resolve to no subject → notes under dict-only subjects silently dropped.
3. `find_taxonomy_path` checked the subject against the *global* subject list only, never the grade's own list → search entries still created → build's `unplaced` check passed.

**Fix**:
- `taxonomy.json` rebuilt clean: dict entries stripped, missing string subjects added per legacy placement (`english` primary/6, `science` intermediate/1–2, `english`+`science` scientific/5).
- 12 literary notes re-subjected (`social` → `geography`/`history`/`economics` per actual titles).
- `ingest.py`: append `sub["id"]`, not raw dict.
- `schema.py` `find_taxonomy_path`: requires `subject_id in grade["subjects"]`.
- `validate.py`: errors on non-string taxonomy subject entries.
- Catalog rebuilt: notes v6, catalogVersion 9 — **574/574 notes in tree**, parsecheck OK, `validate --strict` 0 errors/warnings.

---

## 6. Duplicates & Orphans

- **Exact duplicates (SHA-256)**: 8 thumbnail groups / 23 files / ≈296 KB redundant — keep (evidence of duplicate books; content-addressed).
- **Orphan files**: 0 (every tracked file is reachable from a manifest or is tooling/docs).
- **Untracked**: 0 after cleanup (audit tmp scripts deleted; superseded by `tools/audit.py`).
- **PDF/Word binaries in repo**: 0 — all PDFs are external (h1.iraqiteacher.com); repo holds only JSON/JPG/tooling.

---

## 7. Content Integrity

- 135 book + 574 note manifests: unique ids, valid id formats, valid taxonomy paths, allowed statuses.
- **URLs**: 1,283 total, 2 hosts (`h1.iraqiteacher.com` 709, `iraqiteacher.com` 574), all absolute https, 0 relative, 0 non-https.
- **Liveness** (network check 2026-08-19): 703/709 pdf_urls live and return `%PDF`; **6 dead** — the known relative-URL books (`prep-grade-6-arabic-109/110`, `prep-grade-6-english-111/112`, `prep-grade-6-english-literature-131/132` — h1.iraqiteacher.com/uploaded/… returns 404). These books have status `active` but no downloadable PDF; consider marking `broken` or fixing URLs. **Action recommended** (content decision, not performed).
- Arabic titles: 0 remaining double-whitespace anomalies.
- Generated artifacts: sha256 in `.catalog_state.json`/`manifest.json` match bytes; `build --check` clean.

---

## 8. Security

- **Secrets scan (tracked tree + full history)**: clean — no `ghp_`, `AKIA`, private keys, or API-key patterns.
- **CI token**: `permissions: contents: read` (least privilege) — already correct.
- **RLS/policy concerns**: N/A (no DB in this repo).
- **Known limitation**: git history contains the repo's original file layout; deleting a file does not purge history (no sensitive data found, so history rewrite is unnecessary).
- **Recommendations**: enable GitHub security features (dependabot alerts for `github-actions` already added via config; consider GHAS secret scanning) — requires repo-admin (no `gh` CLI authenticated here).

---

## 9. GitHub Actions / CI

Current workflow (`content-ci.yml`) after hardening:
- `actions/checkout` pinned to `11d5960a…` (v4.2.2), `actions/setup-python` pinned to `a26af69b…` (v5.6.0) — full SHAs.
- `permissions: contents: read`; `concurrency` group with cancel-in-progress.
- Steps: `validate --strict` → `build --check` → `audit.py` health/duplicates/orphans/urls/documents.
- `.github/dependabot.yml` added (weekly, github-actions, prefix `ci`).

**Performance**: single job, ~30 s runtime; no matrix needed. Cache not worth adding for a 30 MB checkout.

---

## 10. Repository Size & Performance

| Metric | Value | Limit | Headroom |
|---|---|---|---|
| Working tree | 16.2 MB | 1 GB (rec.) | 60x |
| `.git` | 14.7 MB (2 packs, 1,999 objects) | 5 GB (strong rec.) | 340x |
| Largest blob | 753 KB (`catalog/notes.json`) | 50 MiB warn | 66x |
| Largest file | 327 KB (`legacy/notes.json`) | — | — |
| Count | 1,222 tracked files | 100k | 80x |
| Clone time | ≈ 5 s | — | — |

No action needed. Re-check yearly.

---

## 11. Future Scale (10k / 50k / 100k items)

- **10k notes** (~2× today's combined catalog): JSON grows to ≈ 4–5 MB total; still fine; keep compact JSON + gzip (already used by app).
- **50k**: ≈ 20–25 MB JSON; sha256/gzip still fine; search_index should move to a compressed or split format; consider pgvector/Supabase if app search needs beyond client-side.
- **100k**: catalog JSON ≈ 40–50 MB, unpacked parse on device becomes a concern — split by stage (primary/intermediate/preparatory) or by grade; consider incremental manifests.
- Binary assets (PDFs) must NEVER enter the repo — always external CDN; thumbs at 300 px ≈ 30 KB each ⇒ 100k = 3 GB → switch to on-demand generation or WebP at that scale.
- Recommend re-running this audit at each milestone (the `tools/audit.py health` check reports size metrics).

---

## 12. Remaining Risks / Recommendations

| # | Item | Owner | Priority |
|---|---|---|---|
| 1 | 6 books with dead pdf_urls (prep-grade-6 relative URLs) — mark `broken` or fix | content owner | High |
| 2 | No branch protection on `main` (CI can be bypassed) | repo admin | High |
| 3 | No GitHub topics / about metadata; no releases page | repo admin | Low |
| 4 | Play-Console-style secret scanning not enabled | repo admin | Medium |
| 5 | 197 notes without local thumbs (network fallback only) | content tooling | Low |
| 6 | 17 shared pdf_url groups + 8 thumbnail dup groups = duplicate-book evidence — dedupe catalog entries | content owner | Medium |
| 7 | No automated `check_links.py` in CI (needs network; could run weekly schedule) | maintainer | Low |

---

## 13. Final State

- `main` @ `HEAD` = clean; `git diff --check` clean; `validate --strict` 0 errors/0 warnings; `build --check` OK; parsecheck OK.
- Catalog: books v6 (unchanged), notes v6 (was 5), catalogVersion 9 (was 8), search 709 entries.
- Automated health tool: `python tools/audit.py health|duplicates|orphans|urls|documents|clean-check`.