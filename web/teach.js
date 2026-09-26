(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;

  const languageSel = document.getElementById("language");
  const categorySel = document.getElementById("category");
  const subcategoryInput = document.getElementById("subcategory");
  const toneInput = document.getElementById("tone");
  const notesInput = document.getElementById("notes");
  const turnsContainer = document.getElementById("turns-container");
  const addTurnBtn = document.getElementById("add-turn-btn");
  const saveBtn = document.getElementById("save-btn");
  const clearBtn = document.getElementById("clear-btn");
  const resultMsg = document.getElementById("result-msg");
  const ownerKeyInput = document.getElementById("owner-key");

  // The owner types the key; it is never part of any page source. It is kept only for this
  // browser tab session (sessionStorage) and sent solely as the X-Owner-Key header on /owner/*.
  try {
    localStorage.removeItem("rupsaa_owner_key"); // older versions kept it permanently
    ownerKeyInput.value = sessionStorage.getItem("rupsaa_owner_key") || "";
  } catch (e) {
    /* storage unavailable */
  }
  ownerKeyInput.addEventListener("input", () => {
    try {
      sessionStorage.setItem("rupsaa_owner_key", ownerKeyInput.value);
    } catch (e) {
      /* storage unavailable */
    }
  });

  function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (ownerKeyInput.value.trim()) headers["X-Owner-Key"] = ownerKeyInput.value.trim();
    return headers;
  }

  function showResult(kind, text) {
    resultMsg.innerHTML = "";
    if (!text) return;
    const div = document.createElement("div");
    div.className = `owner-msg ${kind}`;
    div.textContent = text;
    resultMsg.appendChild(div);
  }

  function addTurn(userText, rupsaaText) {
    const index = turnsContainer.children.length + 1;
    const block = document.createElement("div");
    block.className = "turn-block";
    block.innerHTML = `
      <div class="turn-label">Turn ${index}</div>
      <button type="button" class="remove-turn-btn" title="Remove this turn">✕ remove</button>
      <div class="owner-field">
        <label>User message</label>
        <textarea class="turn-user" placeholder="What the user says…"></textarea>
      </div>
      <div class="owner-field" style="margin-bottom:0">
        <label>Rupsaa response</label>
        <textarea class="turn-rupsaa" placeholder="How Rupsaa replies…"></textarea>
      </div>
    `;
    block.querySelector(".turn-user").value = userText || "";
    block.querySelector(".turn-rupsaa").value = rupsaaText || "";
    block.querySelector(".remove-turn-btn").addEventListener("click", () => {
      if (turnsContainer.children.length <= 1) return; // always keep at least one turn
      block.remove();
      renumberTurns();
    });
    turnsContainer.appendChild(block);
  }

  function renumberTurns() {
    [...turnsContainer.children].forEach((block, i) => {
      block.querySelector(".turn-label").textContent = `Turn ${i + 1}`;
    });
  }

  function collectTurns() {
    return [...turnsContainer.children].map((block) => ({
      user: block.querySelector(".turn-user").value,
      rupsaa: block.querySelector(".turn-rupsaa").value,
    }));
  }

  function resetForm() {
    turnsContainer.innerHTML = "";
    addTurn();
    subcategoryInput.value = "";
    toneInput.value = "";
    notesInput.value = "";
    showResult(null, "");
  }

  async function loadTaxonomy() {
    try {
      const res = await fetch(`${API_URL}/owner/teach/taxonomy`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();

      languageSel.innerHTML = "";
      data.languages.forEach((lang) => {
        const opt = document.createElement("option");
        opt.value = lang;
        opt.textContent = lang;
        languageSel.appendChild(opt);
      });

      categorySel.innerHTML = "";
      data.categories.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.slug;
        opt.title = cat.description;
        opt.textContent = cat.slug;
        categorySel.appendChild(opt);
      });
    } catch (err) {
      showResult("error", `Couldn't load taxonomy from ${API_URL}/owner/teach/taxonomy. Is the backend running?`);
    }
  }

  async function saveExample() {
    const turns = collectTurns();
    if (turns.length === 0 || turns.every((t) => !t.user.trim() && !t.rupsaa.trim())) {
      showResult("error", "Add at least one USER + RUPSAA turn before saving.");
      return;
    }

    saveBtn.disabled = true;
    showResult(null, "");

    const payload = {
      turns,
      language: languageSel.value,
      category: categorySel.value,
      subcategory: subcategoryInput.value.trim() || null,
      tone: toneInput.value.trim() || null,
      notes: notesInput.value.trim() || null,
    };

    try {
      const res = await fetch(`${API_URL}/owner/teach/examples`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });

      if (res.status === 401) {
        showResult("error", "Rejected: missing or invalid owner key. Enter the correct key above.");
        return;
      }

      const data = await res.json();

      if (!data.success) {
        showResult("error", "Not saved:\n" + data.errors.join("\n"));
        return;
      }

      let msg = `Saved as draft — id ${data.conversation_id}.`;
      if (data.warnings && data.warnings.length) {
        msg += "\n\nWarnings:\n" + data.warnings.join("\n");
        showResult("warning", msg);
      } else {
        showResult("success", msg);
      }
      resetForm();
    } catch (err) {
      showResult("error", `Request failed: ${err.message}`);
    } finally {
      saveBtn.disabled = false;
    }
  }

  addTurnBtn.addEventListener("click", () => addTurn());
  saveBtn.addEventListener("click", saveExample);
  clearBtn.addEventListener("click", resetForm);

  loadTaxonomy();
  addTurn();
})();
