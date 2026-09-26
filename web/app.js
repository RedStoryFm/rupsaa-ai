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

  const CHAT_TIMEOUT_MS = 180000; // generation is queued on one GPU; the web proxy waits up to 300 s

  function friendlyError(status, detail) {
    if (status === 429) return detail || "Too many messages — please wait a moment.";
    if (status === 503) return detail || "Rupsaa is starting up — please try again in a minute.";
    if (status === 413) return "That message is too long.";
    if (status === 422) return "That message couldn't be sent (too long or empty).";
    if (status >= 500) return "Something went wrong on our side — please try again.";
    return detail || `status ${status}`;
  }

  async function checkHealth() {
    try {
      const res = await fetch(`${API_URL}/health`, { method: "GET" });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      statusLine.textContent = data.model_loaded
        ? "online"
        : data.model_loading
          ? "starting up (loading the model)…"
          : "online (model loads on first message)";
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

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          use_rag: ragToggle.checked,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(friendlyError(res.status, errBody.detail));
      }

      const data = await res.json();
      conversationId = data.conversation_id;
      removeTypingIndicator();
      appendBubble("assistant", data.response, data.sources);
    } catch (err) {
      removeTypingIndicator();
      if (err.name === "AbortError") {
        showError("Rupsaa is taking too long to answer — please try again.");
      } else if (err instanceof TypeError) {
        showError("Network problem — check your connection and try again.");
      } else {
        showError(`Message failed: ${err.message}`);
      }
    } finally {
      clearTimeout(timer);
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
