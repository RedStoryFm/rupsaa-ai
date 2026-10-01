// Rupsaa Knowledge → General Knowledge tab: create / edit / delete / enable, search + category/tag filters,
// retrieval test, import (CSV / XLSX / JSON) with preview, export and full knowledge backup.
// Talks to /owner/general* (api/owner_routes.py). Changes are live on the next chat message.
(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;
  const $ = (id) => document.getElementById(id);
  const tab = $("tab-general");
  const section = $("general-section");
  if (!tab || !section) return;
  const OTHER = [["tab-docs", "docs-section"], ["tab-terms", "terms-section"], ["tab-dance", "dance-section"]];
  const LIST_FIELDS = { aliases: "gk-aliases", key_points: "gk-key-points", steps: "gk-steps", do: "gk-do", dont: "gk-dont" };
  const TEXT_FIELDS = { title: "gk-title", category: "gk-category", subcategory: "gk-subcategory", summary: "gk-summary",
    description: "gk-description", answer_guidance: "gk-guidance" };
  let editingId = null;
  let importFile = null;
  let meta = { categories: [], languages: ["en", "bn", "banglish"], tags: [] };

  function authHeaders(json = true) {
    const h = json ? { "Content-Type": "application/json" } : {};
    const key = $("owner-key").value.trim();
    if (key) h["X-Owner-Key"] = key;
    return h;
  }
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  function msg(el, kind, text) {
    el.innerHTML = text ? `<div class="owner-msg ${kind}">${esc(text)}</div>` : "";
  }
  const lines = (t) => t.split(/\n/).map((s) => s.trim()).filter(Boolean);
  async function apiError(res) {
    if (res.status === 401) return "missing or invalid owner key";
    const b = await res.json().catch(() => ({}));
    return b.detail || `status ${res.status}`;
  }

  // --- tab: this module hides the others, and any other tab hides this one ---------------------------------
  function select() {
    OTHER.forEach(([t, s]) => {
      if ($(s)) $(s).hidden = true;
      if ($(t)) { $(t).classList.remove("active"); $(t).setAttribute("aria-selected", "false"); }
    });
    section.hidden = false;
    tab.classList.add("active");
    tab.setAttribute("aria-selected", "true");
    try { localStorage.setItem("rupsaa_knowledge_tab", "general"); } catch (e) { /* ignore */ }
    loadMeta().then(load);
  }
  OTHER.forEach(([t]) => $(t) && $(t).addEventListener("click", () => {
    section.hidden = true;
    tab.classList.remove("active");
    tab.setAttribute("aria-selected", "false");
  }));

  // --- meta / form ----------------------------------------------------------------------------------------
  async function loadMeta() {
    try {
      const res = await fetch(`${API_URL}/owner/general/meta`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      meta = await res.json();
    } catch (e) { /* list shows the error */ }
    const cat = $("gk-category"), fcat = $("gk-filter-category"), ftag = $("gk-filter-tag");
    const keepCat = cat.value, keepF = fcat.value, keepT = ftag.value;
    cat.innerHTML = meta.categories.map((c) => `<option>${esc(c)}</option>`).join("");
    cat.value = keepCat || "Custom";
    fcat.innerHTML = `<option value="">All categories</option>` +
      meta.categories.map((c) => `<option value="${esc(c)}">${esc(c)}${meta.counts ? ` (${meta.counts[c] || 0})` : ""}</option>`).join("");
    fcat.value = keepF;
    ftag.innerHTML = `<option value="">All tags</option>` + (meta.tags || []).map((t) => `<option>${esc(t)}</option>`).join("");
    ftag.value = keepT;
    if (!$("gk-languages").children.length) renderLangs(null);
  }
  function renderLangs(selected) {
    const box = $("gk-languages");
    box.innerHTML = "";
    (meta.languages || ["en", "bn", "banglish"]).forEach((l) => {
      const lab = document.createElement("label");
      lab.className = "owner-check-inline";
      lab.style.marginTop = "0";
      lab.innerHTML = `<input type="checkbox" value="${esc(l)}"> ${esc(l)}`;
      lab.querySelector("input").checked = !selected || selected.includes(l);
      box.appendChild(lab);
    });
  }
  function reset() {
    editingId = null;
    $("gk-form-title").textContent = "New knowledge";
    $("gk-save-btn").textContent = "Save knowledge";
    $("gk-cancel-btn").hidden = true;
    Object.values(TEXT_FIELDS).forEach((id) => { if (id !== "gk-category") $(id).value = ""; });
    $("gk-category").value = "Custom";
    Object.values(LIST_FIELDS).forEach((id) => ($(id).value = ""));
    $("gk-tags").value = "";
    $("gk-enabled").checked = true;
    $("gk-source-type").value = "owner";
    $("gk-verified").checked = false;
    $("gk-sources").value = "";
    renderLangs(null);
  }
  function payload() {
    const p = {};
    Object.entries(TEXT_FIELDS).forEach(([k, id]) => (p[k] = $(id).value.trim()));
    Object.entries(LIST_FIELDS).forEach(([k, id]) => (p[k] = lines($(id).value)));
    p.tags = $("gk-tags").value.split(",").map((s) => s.trim()).filter(Boolean);
    p.languages = [...$("gk-languages").querySelectorAll("input:checked")].map((i) => i.value);
    p.enabled = $("gk-enabled").checked;
    p.source_type = $("gk-source-type").value;
    p.verified = $("gk-verified").checked;
    p.sources = lines($("gk-sources").value).map((url) => ({ url }));
    return p;
  }
  async function save() {
    const p = payload();
    if (!p.title || !(p.summary || p.description || p.key_points.length)) {
      msg($("gk-result-msg"), "error", "Title and a summary, description or key points are required.");
      return;
    }
    try {
      const res = await fetch(editingId ? `${API_URL}/owner/general/${encodeURIComponent(editingId)}` : `${API_URL}/owner/general`,
        { method: editingId ? "PUT" : "POST", headers: authHeaders(), body: JSON.stringify(p) });
      if (!res.ok) throw new Error(await apiError(res));
      const r = await res.json();
      msg($("gk-result-msg"), "success", `${editingId ? "Updated" : "Saved"} "${r.title}" (${r.id}) — live on the next chat message.`);
      reset();
      loadMeta().then(load);
    } catch (e) {
      msg($("gk-result-msg"), "error", `Save failed: ${e.message}`);
    }
  }
  async function edit(id) {
    try {
      const res = await fetch(`${API_URL}/owner/general/${encodeURIComponent(id)}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      editingId = d.id;
      Object.entries(TEXT_FIELDS).forEach(([k, elId]) => ($(elId).value = d[k] || ""));
      Object.entries(LIST_FIELDS).forEach(([k, elId]) => ($(elId).value = (d[k] || []).join("\n")));
      $("gk-tags").value = (d.tags || []).join(", ");
      $("gk-enabled").checked = d.enabled;
      $("gk-source-type").value = d.source_type || "owner";
      $("gk-verified").checked = !!d.verified;
      $("gk-sources").value = (d.sources || []).map((x) => x.url).join("\n");
      renderLangs(d.languages);
      $("gk-form-title").textContent = `Edit — ${d.title} (revision ${d.revision})`;
      $("gk-save-btn").textContent = "Save changes";
      $("gk-cancel-btn").hidden = false;
      $("gk-form-title").scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      msg($("gk-result-msg"), "error", `Couldn't load: ${e.message}`);
    }
  }
  async function toggle(d) {
    try {
      const res = await fetch(`${API_URL}/owner/general/${encodeURIComponent(d.id)}`,
        { method: "PUT", headers: authHeaders(), body: JSON.stringify({ enabled: !d.enabled }) });
      if (!res.ok) throw new Error(await apiError(res));
      load();
    } catch (e) {
      msg($("gk-result-msg"), "error", `Update failed: ${e.message}`);
    }
  }
  async function del(d) {
    if (!confirm(`Delete "${d.title}" (${d.id})? A copy is kept in knowledge/general/.history.`)) return;
    try {
      const res = await fetch(`${API_URL}/owner/general/${encodeURIComponent(d.id)}?confirm=true`, { method: "DELETE", headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      if (editingId === d.id) reset();
      loadMeta().then(load);
    } catch (e) {
      msg($("gk-result-msg"), "error", `Delete failed: ${e.message}`);
    }
  }

  // --- list -----------------------------------------------------------------------------------------------
  async function load() {
    const list = $("gk-list");
    list.innerHTML = `<div class="empty-state">Loading…</div>`;
    const qs = new URLSearchParams({ q: $("gk-search").value.trim(), category: $("gk-filter-category").value, tag: $("gk-filter-tag").value });
    try {
      const res = await fetch(`${API_URL}/owner/general?${qs}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      $("gk-count").textContent = `(${d.count})`;
      list.innerHTML = d.records.length ? "" : `<div class="empty-state">No knowledge yet — add some above or import a file.</div>`;
      d.records.forEach((r) => {
        const row = document.createElement("div");
        row.className = "doc-row";
        const meta2 = [r.category + (r.subcategory ? ` / ${r.subcategory}` : ""), r.id, r.aliases.length && `aliases: ${r.aliases.slice(0, 6).join(", ")}`,
          r.tags.length && `tags: ${r.tags.join(", ")}`, `${r.source_type || "owner"}${r.verified ? " ✓" : ""} · rev ${r.revision}`].filter(Boolean).map(esc).join(" · ");
        row.innerHTML = `<div class="doc-info"><div class="doc-title">${esc(r.title)}${r.enabled ? "" : `<span class="badge readonly">disabled</span>`}</div>
          <div class="doc-meta">${meta2}</div><div class="term-def">${esc(r.summary || r.description)}</div></div><div class="doc-actions"></div>`;
        const acts = row.querySelector(".doc-actions");
        [["Edit", "secondary", () => edit(r.id)], [r.enabled ? "Disable" : "Enable", "secondary", () => toggle(r)],
          ["Delete", "danger", () => del(r)]].forEach(([label, kind, fn]) => {
          const b = document.createElement("button");
          b.className = `owner-btn ${kind}`;
          b.textContent = label;
          b.addEventListener("click", fn);
          acts.appendChild(b);
        });
        list.appendChild(row);
      });
    } catch (e) {
      list.innerHTML = `<div class="empty-state">Couldn't load knowledge: ${esc(e.message)}</div>`;
    }
  }

  // --- retrieval test -------------------------------------------------------------------------------------
  async function test() {
    const m = $("gk-test-input").value.trim();
    if (!m) return;
    try {
      const res = await fetch(`${API_URL}/owner/general/lookup?message=${encodeURIComponent(m)}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      const found = d.matches.length ? d.matches.map((x) => `${x.record_id} [${x.source}, ${x.match}, score ${x.score}]`).join("; ") : "none";
      msg($("gk-test-result"), d.matches.length ? "success" : "warning", `Route: ${d.route} — ${d.reason}. Local knowledge: ${found}.`);
    } catch (e) {
      msg($("gk-test-result"), "error", `Check failed: ${e.message}`);
    }
  }

  // --- import / export ------------------------------------------------------------------------------------
  async function download(url, filename) {
    try {
      const res = await fetch(url, { headers: authHeaders(false) });
      if (!res.ok) throw new Error(await apiError(res));
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
      msg($("gk-import-msg"), "error", `Export failed: ${e.message}`);
    }
  }
  async function preview() {
    importFile = $("gk-import-file").files[0] || null;
    if (!importFile) return;
    const body = new FormData();
    body.append("file", importFile);
    try {
      const res = await fetch(`${API_URL}/owner/general/import/preview`, { method: "POST", headers: authHeaders(false), body });
      if (!res.ok) throw new Error(await apiError(res));
      const d = await res.json();
      $("gk-import-counts").innerHTML = Object.entries({ total: d.total, ...d.counts })
        .map(([k, v]) => `<span class="import-count"><strong>${v}</strong> ${esc(k.replace(/_/g, " "))}</span>`).join("");
      $("gk-import-rows").innerHTML = "";
      d.rows.forEach((r) => {
        const tr = document.createElement("tr");
        const details = [...r.errors, ...r.warnings].map(esc).join("<br>") || esc((r.data.summary || r.data.description || "").slice(0, 140));
        const action = r.status === "existing_match"
          ? `<select class="gk-row-action" data-row="${r.row}"><option value="skip">SKIP</option><option value="update">UPDATE</option></select>`
          : r.status === "invalid" || r.status === "duplicate_in_file" ? "—" : "create";
        tr.innerHTML = `<td>${r.row}</td><td>${esc(r.data.title || "")}</td><td>${esc(r.status)}</td><td>${details}</td><td>${action}</td>`;
        $("gk-import-rows").appendChild(tr);
      });
      $("gk-import-preview").hidden = false;
      msg($("gk-import-msg"), "", "");
    } catch (e) {
      msg($("gk-import-msg"), "error", `Preview failed: ${e.message}`);
    }
  }
  async function commit() {
    if (!importFile) return;
    const body = new FormData();
    body.append("file", importFile);
    body.append("update_rows", [...document.querySelectorAll(".gk-row-action")].filter((s) => s.value === "update").map((s) => s.dataset.row).join(","));
    try {
      const res = await fetch(`${API_URL}/owner/general/import`, { method: "POST", headers: authHeaders(false), body });
      if (!res.ok) throw new Error(await apiError(res));
      const c = (await res.json()).counts;
      msg($("gk-import-msg"), "success", `Imported: ${c.created} created, ${c.updated} updated, ${c.skipped} skipped, ${c.failed} failed.`);
      $("gk-import-preview").hidden = true;
      $("gk-import-file").value = "";
      importFile = null;
      loadMeta().then(load);
    } catch (e) {
      msg($("gk-import-msg"), "error", `Import failed: ${e.message}`);
    }
  }

  // --- wiring ---------------------------------------------------------------------------------------------
  tab.addEventListener("click", select);
  $("gk-save-btn").addEventListener("click", save);
  $("gk-cancel-btn").addEventListener("click", reset);
  $("gk-test-btn").addEventListener("click", test);
  $("gk-test-input").addEventListener("keydown", (e) => e.key === "Enter" && test());
  document.querySelectorAll("[data-gk-export]").forEach((b) => b.addEventListener("click",
    () => download(`${API_URL}/owner/general/export.${b.dataset.gkExport}`, `general_knowledge.${b.dataset.gkExport}`)));
  $("gk-backup-btn").addEventListener("click", () => download(`${API_URL}/owner/knowledge/backup`, "rupsaa_knowledge_backup.json"));
  $("gk-import-file").addEventListener("change", preview);
  $("gk-import-commit-btn").addEventListener("click", commit);
  $("gk-import-cancel-btn").addEventListener("click", () => {
    $("gk-import-preview").hidden = true;
    $("gk-import-file").value = "";
    importFile = null;
  });
  let t = null;
  $("gk-search").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
  $("gk-filter-category").addEventListener("change", load);
  $("gk-filter-tag").addEventListener("change", load);
  reset();
  let saved = null;
  try { saved = localStorage.getItem("rupsaa_knowledge_tab"); } catch (e) { /* ignore */ }
  if (saved === "general" || location.hash === "#general") select();
})();
