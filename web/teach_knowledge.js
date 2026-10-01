// Teach Rupsaa → "Teach knowledge": owner adds a General Knowledge record without code or training.
// Same backend as the Knowledge Manager (/owner/general): validated, duplicate-protected, live on the next chat message.
(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;
  const $ = (id) => document.getElementById(id);
  if (!$("tk-save-btn")) return;
  const LIST = { aliases: "tk-aliases", key_points: "tk-key-points", steps: "tk-steps" };
  const TEXT = { title: "tk-title", category: "tk-category", subcategory: "tk-subcategory", summary: "tk-summary",
    description: "tk-description", answer_guidance: "tk-guidance" };

  function headers(json = true) {
    const h = json ? { "Content-Type": "application/json" } : {};
    const key = $("owner-key").value.trim();
    if (key) h["X-Owner-Key"] = key;
    return h;
  }
  function msg(kind, text) {
    const d = document.createElement("div");
    d.className = `owner-msg ${kind}`;
    d.textContent = text;
    $("tk-result-msg").replaceChildren(...(text ? [d] : []));
  }
  const lines = (t) => t.split(/\n/).map((s) => s.trim()).filter(Boolean);
  function payload() {
    const p = {};
    Object.entries(TEXT).forEach(([k, id]) => (p[k] = $(id).value.trim()));
    Object.entries(LIST).forEach(([k, id]) => (p[k] = lines($(id).value)));
    p.tags = $("tk-tags").value.split(",").map((s) => s.trim()).filter(Boolean);
    p.enabled = $("tk-enabled").checked;
    p.source = "owner via Teach page";
    return p;
  }
  function problems(p) {
    const out = [];
    if (!p.title) out.push("Title is required.");
    if (!(p.summary || p.description || p.key_points.length)) out.push("Add a summary, details or key points.");
    return out;
  }
  function preview() {
    const p = payload();
    const parts = [`Title: ${p.title || "—"}`, `Category: ${p.category}${p.subcategory ? " / " + p.subcategory : ""}`];
    if (p.aliases.length) parts.push(`Aliases: ${p.aliases.join(", ")}`);
    if (p.summary) parts.push(`Summary: ${p.summary}`);
    if (p.description) parts.push(`Details: ${p.description}`);
    if (p.key_points.length) parts.push("Key points:\n" + p.key_points.map((x) => `- ${x}`).join("\n"));
    if (p.steps.length) parts.push("Steps:\n" + p.steps.map((x, i) => `${i + 1}. ${x}`).join("\n"));
    if (p.answer_guidance) parts.push(`Answer guidance: ${p.answer_guidance}`);
    if (!p.enabled) parts.push("(disabled — saved but not used in chat)");
    const bad = problems(p);
    $("tk-preview").textContent = parts.join("\n") + (bad.length ? `\n\n⚠ ${bad.join(" ")}` : "");
  }
  async function loadCategories() {
    try {
      const res = await fetch(`${API_URL}/owner/general/meta`, { headers: headers() });
      const cats = res.ok ? (await res.json()).categories : ["Custom"];
      $("tk-category").innerHTML = cats.map((c) => `<option>${c.replace(/</g, "&lt;")}</option>`).join("");
      $("tk-category").value = "Custom";
    } catch (e) {
      $("tk-category").innerHTML = "<option>Custom</option>";
    }
    preview();
  }
  async function save() {
    const p = payload();
    const bad = problems(p);
    if (bad.length) return msg("error", bad.join(" "));
    try {
      const existing = await fetch(`${API_URL}/owner/general?q=${encodeURIComponent(p.title)}`, { headers: headers() });
      if (existing.ok) {
        const same = (await existing.json()).records.find((r) => r.title.toLowerCase() === p.title.toLowerCase());
        if (same && !confirm(`"${same.title}" already exists (${same.id}). Update it with this content? A backup of the old version is kept.`)) return;
        if (same) {
          const res = await fetch(`${API_URL}/owner/general/${encodeURIComponent(same.id)}`, { method: "PUT", headers: headers(), body: JSON.stringify(p) });
          if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `status ${res.status}`);
          return verify(await res.json(), "Updated");
        }
      }
      const res = await fetch(`${API_URL}/owner/general`, { method: "POST", headers: headers(), body: JSON.stringify(p) });
      if (res.status === 401) throw new Error("missing or invalid owner key");
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `status ${res.status}`);
      verify(await res.json(), "Saved");
    } catch (e) {
      msg("error", `Save failed: ${e.message}`);
    }
  }
  async function verify(rec, verb) {
    try {
      const q = `${rec.title} ki?`;
      const res = await fetch(`${API_URL}/owner/general/lookup?message=${encodeURIComponent(q)}`, { headers: headers() });
      const d = res.ok ? await res.json() : { matches: [] };
      const ok = d.matches.some((m) => m.record_id === rec.id);
      msg(ok ? "success" : "warning", `${verb} "${rec.title}" (${rec.id}).` +
        (ok ? ` Retrieval check passed — Rupsaa will use it for "${q}" on the next message.` : " Saved, but the retrieval check didn't find it — check aliases."));
      if (ok) clear();
    } catch (e) {
      msg("success", `${verb} "${rec.title}" (${rec.id}).`);
    }
  }
  function clear() {
    Object.values(TEXT).forEach((id) => { if (id !== "tk-category") $(id).value = ""; });
    Object.values(LIST).forEach((id) => ($(id).value = ""));
    $("tk-tags").value = "";
    $("tk-enabled").checked = true;
    preview();
  }
  document.querySelectorAll("#tk-title,#tk-category,#tk-subcategory,#tk-aliases,#tk-summary,#tk-description,#tk-key-points,#tk-steps,#tk-guidance,#tk-tags,#tk-enabled")
    .forEach((el) => el.addEventListener("input", preview));
  $("tk-save-btn").addEventListener("click", save);
  $("tk-clear-btn").addEventListener("click", () => { clear(); msg("", ""); });
  loadCategories();
})();
