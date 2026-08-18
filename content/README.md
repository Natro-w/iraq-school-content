# content/ — source of truth

Human-edited manifests. Never edit files under `catalog/` directly — run
`python tools/build.py` after changing anything here.

- `taxonomy.json` — canonical stages/branches/grades/subjects. Changing grade or
  subject ids here is a breaking catalog change; validate first.
- `books/{id}/manifest.json` — one file per book. Required fields: `id`, `title`,
  `title_en`, `authors` (list), `stage_id`, `grade_id`, `subject_id`, `pdf_url`
  (absolute https), `status`. Optional: `part`, `parts_total`, `description`,
  `publisher`, `year`, `pages`, `cover_url`, `metadata_url`, `size_bytes`,
  `pdf_sha256`, `license`, `branch_id`, `sort_order`, `added_at`, `updated_at`.
- `notes/{id}/manifest.json` — same taxonomy fields; required: `id`, `title`,
  `author`, `pdf_url`, `status`. Optional: `pages`, `source`, `source_url`,
  `license`, `branch_id`, `sort_order`.

IDs are immutable once shipped. To remove content, set `status: "removed"`
instead of deleting the file (keeps sync history consistent).

Workflow: edit manifest → `python tools/build.py` → `python tools/validate.py --strict`
→ commit everything (content/, catalog/, .catalog_state.json).