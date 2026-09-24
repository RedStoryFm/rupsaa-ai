# Rupsaa terminology

Structured definitions Rupsaa looks up at chat time when someone asks what a
term means ("Strip mane ki?", "what does X mean?", "X বলতে কী বোঝায়?").

- One JSON file per term: `term-<slug>.json` (created by the owner UI —
  web/knowledge.html → **Terminology** tab — or `POST /owner/terminology`).
- Live on the next chat message: no reindex, no restart, no LoRA retraining.
- Rupsaa receives the entry as reference knowledge and explains it in her own
  words/language; nothing here is a canned reply.

Fields: `id, term, aliases[], category, definition, details, answer_guidance,
languages[], example_queries[], tags[], created_at, updated_at, enabled`.
Categories: adult_terminology, creator_platform, dating_relationships, slang, general.
Languages: en, bn, banglish.

Aliases are what make lookups work across languages — add the Banglish and
Bengali forms people actually type (e.g. `strip`, `stripping`, `স্ট্রিপ`).
Files not named `term-*.json` (like this README) are ignored.

## Bulk import (CSV / XLSX)

Terminology tab → **Import Terminology**: download the CSV or XLSX template
(one example row; the XLSX has an "Instructions" sheet), fill one term per
row, choose the file → review the **preview** → **Import Valid Records**.
Multi-value columns use `|`. Rows matching an existing term default to SKIP;
choose UPDATE per row to overwrite (id and created date are kept). Limits:
.csv/.xlsx only, 2 MB, 1000 rows. Implemented in rupsaa/rag/terminology_import.py.
