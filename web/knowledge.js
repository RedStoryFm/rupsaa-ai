(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;

  const categorySel = document.getElementById("doc-category");
  const titleInput = document.getElementById("doc-title");
  const contentInput = document.getElementById("doc-content");
  const notesInput = document.getElementById("doc-notes");
  const formTitle = document.getElementById("form-title");
  const saveBtn = document.getElementById("save-doc-btn");
  const cancelEditBtn = document.getElementById("cancel-edit-btn");
  const docResultMsg = document.getElementById("doc-result-msg");
  const reindexResultMsg = document.getElementById("reindex-result-msg");
  const refreshBtn = document.getElementById("refresh-btn");
  const reindexBtn = document.getElementById("reindex-btn");
  const docListEl = document.getElementById("doc-list");
  const ownerKeyInput = document.getElementById("owner-key");

  ownerKeyInput.value = localStorage.getItem("rupsaa_owner_key") || "";
  ownerKeyInput.addEventListener("input", () => {
    localStorage.setItem("rupsaa_owner_key", ownerKeyInput.value);
  });

  let editingFilename = null; // null = creating a new document

  function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (ownerKeyInput.value.trim()) headers["X-Owner-Key"] = ownerKeyInput.value.trim();
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

  function resetForm() {
    editingFilename = null;
    formTitle.textContent = "New document";
    saveBtn.textContent = "Save document";
    cancelEditBtn.hidden = true;
    titleInput.value = "";
    contentInput.value = "";
    notesInput.value = "";
    if (categorySel.options.length) categorySel.selectedIndex = 0;
    showMsg(docResultMsg, null, "");
  }

  async function loadCategories() {
    try {
      const res = await fetch(`${API_URL}/owner/knowledge/categories`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      categorySel.innerHTML = "";
      data.categories.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat;
        categorySel.appendChild(opt);
      });
    } catch (err) {
      showMsg(docResultMsg, "error", `Couldn't load categories from ${API_URL}. Is the backend running?`);
    }
  }

  async function loadDocuments() {
    docListEl.innerHTML = `<div class="empty-state">Loading…</div>`;
    try {
      const res = await fetch(`${API_URL}/owner/knowledge/documents`, { headers: authHeaders() });
      if (res.status === 401) {
        docListEl.innerHTML = `<div class="empty-state">Missing or invalid owner key — enter it above to view documents.</div>`;
        return;
      }
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      renderDocuments(data.documents);
    } catch (err) {
      docListEl.innerHTML = `<div class="empty-state">Failed to load documents: ${err.message}</div>`;
    }
  }

  function renderDocuments(documents) {
    if (!documents.length) {
      docListEl.innerHTML = `<div class="empty-state">No documents yet.</div>`;
      return;
    }
    docListEl.innerHTML = "";
    documents.forEach((doc) => {
      const row = document.createElement("div");
      row.className = "doc-row";
      const badge = doc.owner_created
        ? `<span class="badge">owner-created</span>`
        : `<span class="badge readonly">pre-existing / read-only</span>`;
      row.innerHTML = `
        <div class="doc-info">
          <div class="doc-title">${escapeHtml(doc.title)}${badge}</div>
          <div class="doc-meta">${escapeHtml(doc.category)} · ${escapeHtml(doc.filename)}</div>
        </div>
        <div class="doc-actions"></div>
      `;
      const actions = row.querySelector(".doc-actions");

      if (doc.owner_created) {
        const editBtn = document.createElement("button");
        editBtn.className = "owner-btn secondary";
        editBtn.textContent = "Edit";
        editBtn.addEventListener("click", () => startEdit(doc.filename));
        actions.appendChild(editBtn);

        const delBtn = document.createElement("button");
        delBtn.className = "owner-btn danger";
        delBtn.textContent = "Delete";
        delBtn.addEventListener("click", () => deleteDocument(doc.filename, doc.title));
        actions.appendChild(delBtn);
      } else {
        const viewBtn = document.createElement("button");
        viewBtn.className = "owner-btn secondary";
        viewBtn.textContent = "View";
        viewBtn.addEventListener("click", () => viewOnly(doc.filename));
        actions.appendChild(viewBtn);
      }

      docListEl.appendChild(row);
    });
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  async function startEdit(filename) {
    try {
      const res = await fetch(`${API_URL}/owner/knowledge/documents/${encodeURIComponent(filename)}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();

      const listRes = await fetch(`${API_URL}/owner/knowledge/documents`, { headers: authHeaders() });
      const listData = await listRes.json();
      const meta = listData.documents.find((d) => d.filename === filename);

      editingFilename = filename;
      formTitle.textContent = `Edit: ${meta ? meta.title : filename}`;
      saveBtn.textContent = "Save changes";
      cancelEditBtn.hidden = false;
      titleInput.value = meta ? meta.title : "";
      categorySel.value = meta ? meta.category : categorySel.value;
      notesInput.value = meta ? meta.source_notes || "" : "";
      contentInput.value = data.content;
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      showMsg(docResultMsg, "error", `Couldn't load document for editing: ${err.message}`);
    }
  }

  async function viewOnly(filename) {
    try {
      const res = await fetch(`${API_URL}/owner/knowledge/documents/${encodeURIComponent(filename)}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      alert(`${filename} (read-only, not created via Rupsaa Knowledge):\n\n${data.content}`);
    } catch (err) {
      showMsg(docResultMsg, "error", `Couldn't load document: ${err.message}`);
    }
  }

  async function deleteDocument(filename, title) {
    if (!confirm(`Delete "${title}" (${filename})? This cannot be undone.`)) return;
    try {
      const res = await fetch(
        `${API_URL}/owner/knowledge/documents/${encodeURIComponent(filename)}?confirm=true`,
        { method: "DELETE", headers: authHeaders() }
      );
      if (res.status === 401) {
        showMsg(docResultMsg, "error", "Rejected: missing or invalid owner key.");
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `status ${res.status}`);
      }
      showMsg(docResultMsg, "success", `Deleted "${title}". Remember to rebuild the RAG index.`);
      loadDocuments();
    } catch (err) {
      showMsg(docResultMsg, "error", `Delete failed: ${err.message}`);
    }
  }

  async function saveDocument() {
    const title = titleInput.value.trim();
    const content = contentInput.value.trim();
    if (!title || !content) {
      showMsg(docResultMsg, "error", "Title and content are required.");
      return;
    }

    saveBtn.disabled = true;
    showMsg(docResultMsg, null, "");

    const payload = {
      title,
      category: categorySel.value,
      content,
      source_notes: notesInput.value.trim() || null,
    };

    try {
      const url = editingFilename
        ? `${API_URL}/owner/knowledge/documents/${encodeURIComponent(editingFilename)}`
        : `${API_URL}/owner/knowledge/documents`;
      const method = editingFilename ? "PUT" : "POST";

      const res = await fetch(url, { method, headers: authHeaders(), body: JSON.stringify(payload) });

      if (res.status === 401) {
        showMsg(docResultMsg, "error", "Rejected: missing or invalid owner key.");
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `status ${res.status}`);
      }

      const data = await res.json();
      showMsg(
        docResultMsg,
        "success",
        `Saved "${data.title}" (${data.filename}). Remember to rebuild the RAG index for changes to take effect in chat.`
      );
      resetForm();
      loadDocuments();
    } catch (err) {
      showMsg(docResultMsg, "error", `Save failed: ${err.message}`);
    } finally {
      saveBtn.disabled = false;
    }
  }

  async function reindex() {
    reindexBtn.disabled = true;
    showMsg(reindexResultMsg, null, "");
    try {
      const res = await fetch(`${API_URL}/owner/knowledge/reindex`, { method: "POST", headers: authHeaders() });
      if (res.status === 401) {
        showMsg(reindexResultMsg, "error", "Rejected: missing or invalid owner key.");
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `status ${res.status}`);
      }
      const data = await res.json();
      showMsg(reindexResultMsg, "success", `Reindexed — ${data.chunks_indexed} chunks indexed.`);
    } catch (err) {
      showMsg(reindexResultMsg, "error", `Reindex failed: ${err.message}`);
    } finally {
      reindexBtn.disabled = false;
    }
  }

  saveBtn.addEventListener("click", saveDocument);
  cancelEditBtn.addEventListener("click", resetForm);
  refreshBtn.addEventListener("click", loadDocuments);
  reindexBtn.addEventListener("click", reindex);

  loadCategories();
  loadDocuments();
})();
