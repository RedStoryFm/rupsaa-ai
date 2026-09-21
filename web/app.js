(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;

  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const resetBtn = document.getElementById("reset-btn");
  const ragToggle = document.getElementById("rag-toggle");
  const statusLine = document.getElementById("status-line");
  const errorBanner = document.getElementById("error-banner");

  let conversationId = null;
  let isSending = false;

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function clearError() {
    errorBanner.hidden = true;
    errorBanner.textContent = "";
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendBubble(role, text, sources) {
    const row = document.createElement("div");
    row.className = `bubble-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.appendChild(bubble);

    if (sources && sources.length > 0) {
      const src = document.createElement("div");
      src.className = "sources";
      src.textContent =
        "Sources: " + sources.map((s) => `${s.source_filename} (${s.score})`).join(", ");
      bubble.appendChild(src);
    }

    messagesEl.appendChild(row);
    scrollToBottom();
    return row;
  }

  function appendTypingIndicator() {
    const row = document.createElement("div");
    row.className = "bubble-row assistant";
    row.id = "typing-indicator";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    bubble.innerHTML = "<span></span><span></span><span></span>";
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const el = document.getElementById("typing-indicator");
    if (el) el.remove();
  }

  function autoResize() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
  }

  async function checkHealth() {
    try {
      const res = await fetch(`${API_URL}/health`, { method: "GET" });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      statusLine.textContent = data.model_loaded ? "online" : "online (model loads on first message)";
    } catch (err) {
      statusLine.textContent = "offline — check backend";
      showError(`Can't reach Rupsaa backend at ${API_URL}. Is the API running?`);
    }
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isSending) return;

    clearError();
    appendBubble("user", text);
    inputEl.value = "";
    autoResize();

    isSending = true;
    sendBtn.disabled = true;
    appendTypingIndicator();

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          use_rag: ragToggle.checked,
        }),
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `status ${res.status}`);
      }

      const data = await res.json();
      conversationId = data.conversation_id;
      removeTypingIndicator();
      appendBubble("assistant", data.response, data.sources);
    } catch (err) {
      removeTypingIndicator();
      showError(`Message failed: ${err.message}`);
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  async function resetConversation() {
    if (conversationId) {
      try {
        await fetch(`${API_URL}/conversation/reset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: conversationId }),
        });
      } catch (err) {
        // Non-fatal — starting a fresh conversation_id client-side still works.
      }
    }
    conversationId = null;
    messagesEl.innerHTML = "";
    clearError();
  }

  sendBtn.addEventListener("click", sendMessage);
  resetBtn.addEventListener("click", resetConversation);
  inputEl.addEventListener("input", autoResize);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  checkHealth();
  inputEl.focus();
})();
