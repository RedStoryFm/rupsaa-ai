// Rupsaa Knowledge → Terminology tab: create / edit / delete / search
// structured term entries, and test how a chat message is routed.
// Talks to /owner/terminology* (api/owner_routes.py). Changes are live on
// the next chat message — no reindex, no retraining.
(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;
  const $ = (id) => document.getElementById(id);

  const tabDocs = $("tab-docs");
  const tabTerms = $("tab-terms");
  const docsSection = $("docs-section");
  const termsSection = $("terms-section");

  const f = {
    title: $("term-form-title"),
    term: $("term-term"),
    category: $("term-category"),
    aliases: $("term-aliases"),
    definition: $("term-definition"),
    details: $("term-details"),
    guidance: $("term-guidance"),
    examples: $("term-examples"),
    tags: $("term-tags"),
    languages: $("term-languages"),
    enabled: $("term-enabled"),
    save: $("save-term-btn"),
    cancel: $("cancel-term-btn"),
    msg: $("term-result-msg"),
  };
  const listEl = $("term-list");
  const searchInput = $("term-search");
  const testInput = $("term-test-input");
  const testResult = $("term-test-result");

  let editingId = null;
  let languages = ["en", "bn", "banglish"];

  function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    const key = $("owner-key").value.trim();
    if (key) headers["X-Owner-Key"] = key;
    return headers;
  }

  function showMsg(el, kind, text) {
    el.innerHTML = "";
    if (!text) return;
    const div = document.createElement("div");
    div.className = `owner-msg ${kind}`;
    div.textContent = text;
    el.appendChild(div);
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function splitList(text) {
    return text
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function apiError(res) {
    if (res.status === 401) return "missing or invalid owner key";
    const body = await res.json().catch(() => ({}));
    return body.detail || `status ${res.status}`;
  }

  // --- tabs ---------------------------------------------------------------

  function selectTab(which) {
    const terms = which === "terms";
    termsSection.hidden = !terms;
    docsSection.hidden = terms;
    // Dance tab (web/dance.js) — hide it whenever Documents or Terminology is chosen.
    if ($("dance-section")) $("dance-section").hidden = true;
    if ($("tab-dance")) {
      $("tab-dance").classList.remove("active");
      $("tab-dance").setAttribute("aria-selected", "false");
    }
    tabTerms.classList.toggle("active", terms);
    tabDocs.classList.toggle("active", !terms);
    tabTerms.setAttribute("aria-selected", String(terms));
    tabDocs.setAttribute("aria-selected", String(!terms));
    try {
      localStorage.setItem("rupsaa_knowledge_tab", which);
    } catch (e) {
      /* storage unavailable — tab choice just isn't remembered */
    }
    if (terms) loadTerms();
  }

  // --- form ---------------------------------------------------------------

  function renderLanguageChecks(selected) {
    f.languages.innerHTML = "";
    languages.forEach((lang) => {
      const label = document.createElement("label");
      label.className = "owner-check-inline";
      label.style.marginTop = "0";
      label.innerHTML = `<input type="checkbox" value="${escapeHtml(lang)}"> ${escapeHtml(lang)}`;
      label.querySelector("input").checked = !selected || selected.includes(lang);
      f.languages.appendChild(label);
    });
  }

  function resetForm() {
    editingId = null;
    f.title.textContent = "New term";
    f.save.textContent = "Save term";
    f.cancel.hidden = true;
    [f.term, f.aliases, f.definition, f.details, f.guidance, f.examples, f.tags].forEach((el) => (el.value = ""));
    f.enabled.checked = true;
    if (f.category.options.length) f.category.selectedIndex = 0;
    renderLanguageChecks(null);
  }

  function formPayload() {
    return {
      term: f.term.value.trim(),
      category: f.category.value,
      aliases: splitList(f.aliases.value),
      definition: f.definition.value.trim(),
      details: f.details.value.trim(),
      answer_guidance: f.guidance.value.trim(),
      example_queries: f.examples.value.split("\n").map((s) => s.trim()).filter(Boolean),
      tags: splitList(f.tags.value),
      languages: [...f.languages.querySelectorAll("input:checked")].map((i) => i.value),
      enabled: f.enabled.checked,
    };
  }

  async function saveTerm() {
    const payload = formPayload();
    if (!payload.term || !payload.definition) {
      showMsg(f.msg, "error", "Term and definition are required.");
      return;
    }
    f.save.disabled = true;
    try {
      const url = editingId
        ? `${API_URL}/owner/terminology/${encodeURIComponent(editingId)}`
        : `${API_URL}/owner/terminology`;
      const res = await fetch(url, {
        method: editingId ? "PUT" : "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await apiError(res));
      const data = await res.json();
      showMsg(f.msg, "success", `Saved "${data.term}" (${data.id}). Live in chat from the next message.`);
      resetForm();
      loadTerms();
    } catch (err) {
      showMsg(f.msg, "error", `Save failed: ${err.message}`);
    } finally {
      f.save.disabled = false;
    }
  }

  async function startEdit(id) {
    try {
      const res = await fetch(`${API_URL}/owner/terminology/${encodeURIComponent(id)}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const t = await res.json();
      editingId = t.id;
      f.title.textContent = `Edit: ${t.term}`;
      f.save.textContent = "Save changes";
      f.cancel.hidden = false;
      f.term.value = t.term;
      f.category.value = t.category;
      f.aliases.value = t.aliases.join("\n");
      f.definition.value = t.definition;
      f.details.value = t.details;
      f.guidance.value = t.answer_guidance;
      f.examples.value = t.example_queries.join("\n");
      f.tags.value = t.tags.join(", ");
      f.enabled.checked = t.enabled;
      renderLanguageChecks(t.languages);
      termsSection.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      showMsg(f.msg, "error", `Couldn't load term: ${err.message}`);
    }
  }

  async function deleteTerm(id, term) {
    if (!confirm(`Delete term "${term}" (${id})? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_URL}/owner/terminology/${encodeURIComponent(id)}?confirm=true`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(await apiError(res));
      showMsg(f.msg, "success", `Deleted "${term}".`);
      if (editingId === id) resetForm();
      loadTerms();
    } catch (err) {
      showMsg(f.msg, "error", `Delete failed: ${err.message}`);
    }
  }

  // --- list ---------------------------------------------------------------

  async function loadTerms() {
    listEl.innerHTML = `<div class="empty-state">Loading…</div>`;
    const q = searchInput.value.trim();
    try {
      const res = await fetch(`${API_URL}/owner/terminology${q ? `?q=${encodeURIComponent(q)}` : ""}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(await apiError(res));
      renderTerms((await res.json()).terms);
    } catch (err) {
      listEl.innerHTML = `<div class="empty-state">Couldn't load terms: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderTerms(terms) {
    if (!terms.length) {
      listEl.innerHTML = `<div class="empty-state">${searchInput.value.trim() ? "No matching terms." : "No terms yet — add one above."}</div>`;
      return;
    }
    listEl.innerHTML = "";
    terms.forEach((t) => {
      const row = document.createElement("div");
      row.className = "doc-row";
      const badge = t.enabled ? "" : `<span class="badge readonly">disabled</span>`;
      const aliases = t.aliases.length ? ` · aliases: ${escapeHtml(t.aliases.slice(0, 6).join(", "))}` : "";
      row.innerHTML = `
        <div class="doc-info">
          <div class="doc-title">${escapeHtml(t.term)}${badge}</div>
          <div class="doc-meta">${escapeHtml(t.category)} · ${escapeHtml(t.id)}${aliases}</div>
          <div class="term-def">${escapeHtml(t.definition)}</div>
        </div>
        <div class="doc-actions"></div>`;
      const actions = row.querySelector(".doc-actions");
      const edit = document.createElement("button");
      edit.className = "owner-btn secondary";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => startEdit(t.id));
      const del = document.createElement("button");
      del.className = "owner-btn danger";
      del.textContent = "Delete";
      del.addEventListener("click", () => deleteTerm(t.id, t.term));
      actions.append(edit, del);
      listEl.appendChild(row);
    });
  }

  // --- routing test ---------------------------------------------------------

  async function testMessage() {
    const message = testInput.value.trim();
    if (!message) return;
    try {
      const res = await fetch(`${API_URL}/owner/terminology/lookup?message=${encodeURIComponent(message)}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      const matches = d.matches.length
        ? d.matches.map((m) => `${m.term} (${m.id}, ${m.method}, score ${m.score})`).join("; ")
        : "none";
      showMsg(
        testResult,
        d.matches.length ? "success" : "warning",
        `Route: ${d.route} — ${d.reason}. Terminology matches: ${matches}. ` +
          `Documents eligible: ${d.documents_eligible ? "yes" : "no"}.`
      );
    } catch (err) {
      showMsg(testResult, "error", `Check failed: ${err.message}`);
    }
  }

  async function loadMeta() {
    try {
      const res = await fetch(`${API_URL}/owner/terminology/meta`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      languages = data.languages;
      f.category.innerHTML = "";
      data.categories.forEach((c) => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        f.category.appendChild(opt);
      });
    } catch (err) {
      showMsg(f.msg, "error", `Couldn't load terminology categories from ${API_URL}. Is the backend running?`);
    }
    renderLanguageChecks(null);
  }

  // --- bulk import (CSV / XLSX) ---------------------------------------------
  // Selecting a file only PREVIEWS it (server validates, nothing is saved).
  // "Import Valid Records" re-sends the same file with the rows the owner
  // switched from SKIP to UPDATE; the server re-validates before writing.

  const imp = {
    file: $("import-file"),
    msg: $("import-msg"),
    preview: $("import-preview"),
    counts: $("import-counts"),
    rows: $("import-rows"),
    bulkRow: $("import-bulk-row"),
    bulk: $("import-bulk-action"),
    commit: $("import-commit-btn"),
    cancel: $("import-cancel-btn"),
  };
  $("tmpl-csv-link").href = `${API_URL}/owner/terminology/template.csv`;
  $("tmpl-xlsx-link").href = `${API_URL}/owner/terminology/template.xlsx`;

  let previewFile = null;
  let previewData = null;

  const STATUS_LABEL = {
    valid: "valid",
    warning: "valid (warning)",
    invalid: "invalid",
    duplicate_in_file: "duplicate in file",
    existing_match: "already exists",
  };

  function uploadHeaders() {
    // No Content-Type: the browser sets the multipart boundary itself.
    const headers = {};
    const key = $("owner-key").value.trim();
    if (key) headers["X-Owner-Key"] = key;
    return headers;
  }

  function resetImport() {
    previewFile = null;
    previewData = null;
    imp.file.value = "";
    imp.preview.hidden = true;
    imp.rows.innerHTML = "";
    imp.counts.innerHTML = "";
  }

  function renderPreview(data) {
    const c = data.counts;
    const chips = [
      ["Total rows", c.total],
      ["Valid", c.valid],
      ["Warnings", c.warnings],
      ["Invalid", c.invalid],
      ["Duplicates", c.duplicates],
    ];
    imp.counts.innerHTML = chips
      .map(([label, n]) => `<span class="import-count"><strong>${n}</strong>${escapeHtml(label)}</span>`)
      .join("");
    imp.bulkRow.hidden = c.existing_matches === 0;
    imp.bulk.value = "skip";
    imp.rows.innerHTML = "";
    data.rows.forEach((r) => {
      const tr = document.createElement("tr");
      const issues = [
        ...r.errors.map((e) => `<div class="import-issue err">${escapeHtml(e)}</div>`),
        ...r.warnings.map((w) => `<div class="import-issue warn">${escapeHtml(w)}</div>`),
      ];
      if (r.status === "existing_match") {
        issues.unshift(`<div class="import-issue">Matches existing term “${escapeHtml(r.existing_term)}” (${escapeHtml(r.existing_id)})</div>`);
      }
      if (!issues.length) {
        const aliases = r.data.aliases && r.data.aliases.length ? ` · aliases: ${r.data.aliases.slice(0, 5).join(", ")}` : "";
        issues.push(`<div class="import-issue">${escapeHtml(r.data.category)}${escapeHtml(aliases)}</div>`);
      }
      let action = "—";
      if (r.status === "existing_match") {
        action = `<select class="import-row-action" data-row="${r.row}">
            <option value="skip" selected>SKIP</option><option value="update">UPDATE</option></select>`;
      } else if (r.status === "valid" || r.status === "warning") {
        action = "create";
      } else {
        action = "not imported";
      }
      tr.innerHTML = `
        <td>${r.row}</td>
        <td>${escapeHtml(r.data.term || "(blank)")}</td>
        <td><span class="import-status ${escapeHtml(r.status)}">${escapeHtml(STATUS_LABEL[r.status] || r.status)}</span></td>
        <td>${issues.join("")}</td>
        <td>${action}</td>`;
      imp.rows.appendChild(tr);
    });
    const importable = c.valid + c.existing_matches;
    imp.commit.disabled = importable === 0;
    imp.preview.hidden = false;
  }

  async function previewImport() {
    const file = imp.file.files[0];
    resetPreviewOnly();
    if (!file) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      showMsg(imp.msg, "error", "Unsupported file type — choose a .csv or .xlsx file.");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showMsg(imp.msg, "error", "File is too large (max 2 MB).");
      return;
    }
    showMsg(imp.msg, "warning", `Checking ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API_URL}/owner/terminology/import/preview`, {
        method: "POST",
        headers: uploadHeaders(),
        body: form,
      });
      if (!res.ok) throw new Error(await apiError(res));
      previewData = await res.json();
      previewFile = file;
      const c = previewData.counts;
      showMsg(
        imp.msg,
        c.invalid ? "warning" : "success",
        `Preview of ${file.name}: nothing has been saved yet. Review the rows below, then click “Import Valid Records”.`
      );
      renderPreview(previewData);
    } catch (err) {
      showMsg(imp.msg, "error", `Preview failed: ${err.message}`);
    }
  }

  function resetPreviewOnly() {
    previewFile = null;
    previewData = null;
    imp.preview.hidden = true;
    imp.rows.innerHTML = "";
    showMsg(imp.msg, null, "");
  }

  async function commitImport() {
    if (!previewFile || !previewData) return;
    const updateRows = [...imp.rows.querySelectorAll(".import-row-action")]
      .filter((sel) => sel.value === "update")
      .map((sel) => sel.dataset.row);
    if (updateRows.length && !confirm(`Overwrite ${updateRows.length} existing term(s) with the values from this file?`)) {
      return;
    }
    const form = new FormData();
    form.append("file", previewFile);
    form.append("update_rows", updateRows.join(","));
    imp.commit.disabled = true;
    try {
      const res = await fetch(`${API_URL}/owner/terminology/import`, {
        method: "POST",
        headers: uploadHeaders(),
        body: form,
      });
      if (!res.ok) throw new Error(await apiError(res));
      const r = await res.json();
      const parts = [`${r.counts.created} created`, `${r.counts.updated} updated`, `${r.counts.skipped} skipped`];
      if (r.counts.failed) parts.push(`${r.counts.failed} failed (${r.failed.map((f) => `row ${f.row}: ${f.error}`).join("; ")})`);
      showMsg(
        imp.msg,
        r.counts.failed ? "warning" : "success",
        `Import finished: ${parts.join(", ")}. Imported terms are live in chat from the next message.`
      );
      resetImport();
      loadTerms();
    } catch (err) {
      showMsg(imp.msg, "error", `Import failed: ${err.message}`);
      imp.commit.disabled = false;
    }
  }

  imp.file.addEventListener("change", previewImport);
  imp.commit.addEventListener("click", commitImport);
  imp.cancel.addEventListener("click", () => {
    resetImport();
    showMsg(imp.msg, null, "");
  });
  imp.bulk.addEventListener("change", () => {
    imp.rows.querySelectorAll(".import-row-action").forEach((sel) => (sel.value = imp.bulk.value));
  });

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadTerms, 250);
  });
  $("term-refresh-btn").addEventListener("click", loadTerms);
  f.save.addEventListener("click", saveTerm);
  f.cancel.addEventListener("click", resetForm);
  $("term-test-btn").addEventListener("click", testMessage);
  testInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") testMessage();
  });
  tabDocs.addEventListener("click", () => selectTab("docs"));
  tabTerms.addEventListener("click", () => selectTab("terms"));

  loadMeta().then(() => {
    let saved = null;
    try {
      saved = localStorage.getItem("rupsaa_knowledge_tab");
    } catch (e) {
      /* ignore */
    }
    if (saved === "terms" || location.hash === "#terminology") selectTab("terms");
  });
})();
