// Rupsaa Knowledge → Dance tab: create / edit / delete / search structured
// dance-style entries, bulk import (CSV / XLSX / JSON), and test retrieval.
// Talks to /owner/dance* (api/owner_routes.py). Changes are live on the next
// chat message — no reindex, no retraining. Nothing is ever filled in for the owner.
(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;
  const $ = (id) => document.getElementById(id);
  const LANGUAGES = ["en", "bn", "banglish"];

  const tab = $("tab-dance");
  const section = $("dance-section");
  const otherSections = ["docs-section", "terms-section"].map($);
  const otherTabs = ["tab-docs", "tab-terms"].map($);

  const TEXT_FIELDS = {
    name: "dance-name", category: "dance-category", origin: "dance-origin", description: "dance-description",
    key_movements: "dance-movements", answer_guidance: "dance-guidance", difficulty: "dance-difficulty",
    prerequisites: "dance-prerequisites", warmup: "dance-warmup", basic_steps: "dance-basic-steps",
    step_sequence: "dance-step-sequence", common_mistakes: "dance-mistakes", practice_tips: "dance-tips",
    source: "dance-source",
  };
  const f = {
    title: $("dance-form-title"), aliases: $("dance-aliases"), tags: $("dance-tags"),
    languages: $("dance-languages"), enabled: $("dance-enabled"), save: $("save-dance-btn"),
    cancel: $("cancel-dance-btn"), msg: $("dance-result-msg"),
  };
  const listEl = $("dance-list");
  const searchInput = $("dance-search");
  let editingId = null;
  let importFile = null;

  function authHeaders(json = true) {
    const headers = json ? { "Content-Type": "application/json" } : {};
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
  const splitList = (text) => text.split(/[\n,|]/).map((s) => s.trim()).filter(Boolean);
  async function apiError(res) {
    if (res.status === 401) return "missing or invalid owner key";
    const body = await res.json().catch(() => ({}));
    return body.detail || `status ${res.status}`;
  }

  // --- tab ------------------------------------------------------------------
  function selectDanceTab() {
    section.hidden = false;
    otherSections.forEach((s) => s && (s.hidden = true));
    otherTabs.forEach((t) => {
      if (!t) return;
      t.classList.remove("active");
      t.setAttribute("aria-selected", "false");
    });
    tab.classList.add("active");
    tab.setAttribute("aria-selected", "true");
    try {
      localStorage.setItem("rupsaa_knowledge_tab", "dance");
    } catch (e) {
      /* storage unavailable */
    }
    loadDances();
  }

  // --- form -----------------------------------------------------------------
  function renderLanguageChecks(selected) {
    f.languages.innerHTML = "";
    LANGUAGES.forEach((lang) => {
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
    f.title.textContent = "New dance";
    f.save.textContent = "Save dance";
    f.cancel.hidden = true;
    Object.values(TEXT_FIELDS).forEach((id) => ($(id).value = ""));
    f.aliases.value = "";
    f.tags.value = "";
    f.enabled.checked = true;
    renderLanguageChecks(null);
  }
  function payload() {
    const p = {};
    Object.entries(TEXT_FIELDS).forEach(([k, id]) => (p[k] = $(id).value.trim()));
    p.aliases = splitList(f.aliases.value);
    p.tags = splitList(f.tags.value);
    p.languages = [...f.languages.querySelectorAll("input:checked")].map((i) => i.value);
    p.enabled = f.enabled.checked;
    return p;
  }
  async function saveDance() {
    const p = payload();
    if (!p.name || !p.description) {
      showMsg(f.msg, "error", "Name and description are required.");
      return;
    }
    try {
      const res = await fetch(editingId ? `${API_URL}/owner/dance/${encodeURIComponent(editingId)}` : `${API_URL}/owner/dance`, {
        method: editingId ? "PUT" : "POST",
        headers: authHeaders(),
        body: JSON.stringify(p),
      });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      showMsg(f.msg, "success", `Saved "${d.name}" (${d.id}). Live in chat from the next message.`);
      resetForm();
      loadDances();
    } catch (err) {
      showMsg(f.msg, "error", `Save failed: ${err.message}`);
    }
  }
  async function startEdit(id) {
    try {
      const res = await fetch(`${API_URL}/owner/dance/${encodeURIComponent(id)}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      editingId = d.id;
      Object.entries(TEXT_FIELDS).forEach(([k, elId]) => ($(elId).value = d[k] || ""));
      f.aliases.value = d.aliases.join("\n");
      f.tags.value = d.tags.join(", ");
      f.enabled.checked = d.enabled;
      renderLanguageChecks(d.languages);
      f.title.textContent = `Edit dance — ${d.name}`;
      f.save.textContent = "Save changes";
      f.cancel.hidden = false;
      f.title.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      showMsg(f.msg, "error", `Couldn't load dance: ${err.message}`);
    }
  }
  async function deleteDance(id, name) {
    if (!confirm(`Delete dance "${name}" (${id})? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_URL}/owner/dance/${encodeURIComponent(id)}?confirm=true`, { method: "DELETE", headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      showMsg(f.msg, "success", `Deleted "${name}".`);
      if (editingId === id) resetForm();
      loadDances();
    } catch (err) {
      showMsg(f.msg, "error", `Delete failed: ${err.message}`);
    }
  }

  // --- list -----------------------------------------------------------------
  async function loadDances() {
    listEl.innerHTML = `<div class="empty-state">Loading…</div>`;
    const q = searchInput.value.trim();
    try {
      const res = await fetch(`${API_URL}/owner/dance${q ? `?q=${encodeURIComponent(q)}` : ""}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      $("dance-count").textContent = `(${d.count})`;
      renderDances(d.dances);
    } catch (err) {
      listEl.innerHTML = `<div class="empty-state">Couldn't load dances: ${escapeHtml(err.message)}</div>`;
    }
  }
  function renderDances(dances) {
    if (!dances.length) {
      listEl.innerHTML = `<div class="empty-state">${searchInput.value.trim() ? "No matching dances." : "No dances yet — add one above or import a file."}</div>`;
      return;
    }
    listEl.innerHTML = "";
    dances.forEach((d) => {
      const row = document.createElement("div");
      row.className = "doc-row";
      const badge = d.enabled ? "" : `<span class="badge readonly">disabled</span>`;
      const meta = [d.origin && `origin: ${d.origin}`, d.category, d.id, d.aliases.length && `aliases: ${d.aliases.slice(0, 6).join(", ")}`]
        .filter(Boolean).map(escapeHtml).join(" · ");
      row.innerHTML = `
        <div class="doc-info">
          <div class="doc-title">${escapeHtml(d.name)}${badge}</div>
          <div class="doc-meta">${meta}</div>
          <div class="term-def">${escapeHtml(d.description)}</div>
        </div>
        <div class="doc-actions"></div>`;
      const actions = row.querySelector(".doc-actions");
      const edit = document.createElement("button");
      edit.className = "owner-btn secondary";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => startEdit(d.id));
      const del = document.createElement("button");
      del.className = "owner-btn danger";
      del.textContent = "Delete";
      del.addEventListener("click", () => deleteDance(d.id, d.name));
      actions.append(edit, del);
      listEl.appendChild(row);
    });
  }

  // --- retrieval test -------------------------------------------------------
  async function testMessage() {
    const message = $("dance-test-input").value.trim();
    const out = $("dance-test-result");
    if (!message) return;
    try {
      const res = await fetch(`${API_URL}/owner/dance/lookup?message=${encodeURIComponent(message)}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      const found = d.matches.length
        ? d.matches.map((m) => `${m.name} (${m.id}, ${m.method}, score ${m.score})`).join("; ")
        : "none";
      showMsg(out, d.matches.length ? "success" : "warning",
        `Route: ${d.route} — ${d.reason}.${d.term_candidate ? ` Asked about: "${d.term_candidate}".` : ""} Dance matches: ${found}.`);
    } catch (err) {
      showMsg(out, "error", `Check failed: ${err.message}`);
    }
  }

  // --- import ---------------------------------------------------------------
  const imp = {
    file: $("dance-import-file"), msg: $("dance-import-msg"), preview: $("dance-import-preview"),
    counts: $("dance-import-counts"), rows: $("dance-import-rows"),
  };
  async function previewImport() {
    importFile = imp.file.files[0] || null;
    imp.preview.hidden = true;
    if (!importFile) return;
    const body = new FormData();
    body.append("file", importFile);
    try {
      const res = await fetch(`${API_URL}/owner/dance/import/preview`, { method: "POST", headers: authHeaders(false), body });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      const c = d.counts;
      imp.counts.innerHTML = ["total", "valid", "warnings", "invalid", "duplicates_in_file", "existing_matches", "missing_origin"]
        .map((k) => `<span class="import-count"><strong>${c[k]}</strong> ${escapeHtml(k.replace(/_/g, " "))}</span>`).join("");
      imp.rows.innerHTML = "";
      d.rows.forEach((r) => {
        const tr = document.createElement("tr");
        const details = [...r.errors, ...r.warnings].map(escapeHtml).join("<br>") ||
          escapeHtml([r.data.origin, r.data.description].filter(Boolean).join(" — ").slice(0, 140));
        const action = r.status === "existing_match"
          ? `<select class="import-row-action" data-row="${r.row}"><option value="skip">SKIP</option><option value="update">UPDATE</option></select>`
          : r.status === "invalid" || r.status === "duplicate_in_file" ? "—" : "create";
        tr.innerHTML = `<td>${r.row}</td><td>${escapeHtml(r.data.name || "")}</td><td>${escapeHtml(r.status)}</td><td>${details}</td><td>${action}</td>`;
        imp.rows.appendChild(tr);
      });
      imp.preview.hidden = false;
      showMsg(imp.msg, "", "");
    } catch (err) {
      showMsg(imp.msg, "error", `Preview failed: ${err.message}`);
    }
  }
  async function commitImport() {
    if (!importFile) return;
    const body = new FormData();
    body.append("file", importFile);
    const updates = [...imp.rows.querySelectorAll(".import-row-action")].filter((s) => s.value === "update").map((s) => s.dataset.row);
    body.append("update_rows", updates.join(","));
    try {
      const res = await fetch(`${API_URL}/owner/dance/import`, { method: "POST", headers: authHeaders(false), body });
      if (!res.ok) throw new Error(await apiError(res));
      const c = (await res.json()).counts;
      showMsg(imp.msg, "success", `Imported: ${c.created} created, ${c.updated} updated, ${c.skipped} skipped, ${c.failed} failed.`);
      imp.preview.hidden = true;
      imp.file.value = "";
      importFile = null;
      loadDances();
    } catch (err) {
      showMsg(imp.msg, "error", `Import failed: ${err.message}`);
    }
  }

  // --- wiring ---------------------------------------------------------------
  $("dance-tmpl-csv-link").href = `${API_URL}/owner/dance/template.csv`;
  $("dance-tmpl-xlsx-link").href = `${API_URL}/owner/dance/template.xlsx`;
  tab.addEventListener("click", selectDanceTab);
  f.save.addEventListener("click", saveDance);
  f.cancel.addEventListener("click", resetForm);
  $("dance-refresh-btn").addEventListener("click", loadDances);
  $("dance-test-btn").addEventListener("click", testMessage);
  $("dance-test-input").addEventListener("keydown", (e) => e.key === "Enter" && testMessage());
  imp.file.addEventListener("change", previewImport);
  $("dance-import-commit-btn").addEventListener("click", commitImport);
  $("dance-import-cancel-btn").addEventListener("click", () => {
    imp.preview.hidden = true;
    imp.file.value = "";
    importFile = null;
  });
  let timer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(loadDances, 250);
  });
  resetForm();
  let saved = null;
  try {
    saved = localStorage.getItem("rupsaa_knowledge_tab");
  } catch (e) {
    /* ignore */
  }
  if (saved === "dance" || location.hash === "#dance") selectDanceTab();
})();
