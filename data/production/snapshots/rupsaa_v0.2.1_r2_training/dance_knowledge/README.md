# Dance knowledge (owner-editable)

One JSON file per dance style (`dance-<slug>.json`), read at chat time by
`rupsaa/rag/dance.py`. Add, edit or disable dances in the owner UI
(`/knowledge.html` → **Dance**), by bulk import (CSV / XLSX / JSON — same tab, or
`python scripts/import_dance_knowledge.py <file> --yes`), or by editing these files.
Changes are live on the next chat message: no reindex, no retraining.

Fields: `name`, `description` (required); `aliases`, `origin`, `category`,
`key_movements`, `answer_guidance`, `languages`, `tags`, `enabled`, `source`.
Optional, for later — fill only with verified content: `difficulty`, `prerequisites`,
`warmup`, `basic_steps`, `step_sequence`, `common_mistakes`, `practice_tips`.

Rupsaa uses only what is written here. Empty step fields are never filled in by the
system; when asked for steps that aren't recorded she says she doesn't have them yet.
