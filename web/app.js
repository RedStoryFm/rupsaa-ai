(function () {
  "use strict";

  const API_URL = window.RUPSAA_CONFIG.apiUrl;

  const messagesEl = document.getElementById("messages");
  const welcomeEl = document.getElementById("welcome");
  const suggestionsEl = document.getElementById("suggestions");
  const inputEl = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const resetBtn = document.getElementById("reset-btn");
  const ragToggle = document.getElementById("rag-toggle");
  const statusLine = document.getElementById("status-line");
  const errorBanner = document.getElementById("error-banner");
  const charCounter = document.getElementById("char-counter");

  const MAX_CHARS = 8000;
  const CHAR_WARN_THRESHOLD = 7000;

  let conversationId = null;
  let isSending = false;
  let rateLimitedUntil = 0;
  let countdownTimer = null;
  let healthPollTimer = null;

  function hideWelcome() {
    welcomeEl.hidden = true;
  }

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

    if (role === "assistant") {
      const meta = document.createElement("div");
      meta.className = "msg-meta";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "copy-btn";
      copyBtn.textContent = "Copy";
      copyBtn.setAttribute("aria-label", "Copy Rupsaa's response");
      copyBtn.addEventListener("click", () => copyText(text, copyBtn));
      meta.appendChild(copyBtn);
      row.appendChild(meta);
    }

    messagesEl.appendChild(row);
    scrollToBottom();
    return row;
  }

  function copyText(text, btn) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => {
      const original = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = original; }, 1500);
    }).catch(() => {});
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

  function setStatus(text, cls) {
    statusLine.textContent = text;
    statusLine.className = `brand-status ${cls}`;
  }

  async function checkHealth() {
    try {
      const res = await fetch(`${API_URL}/health`, { method: "GET" });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();

      if (data.model_loaded) {
        setStatus("online", "status-online");
        stopHealthPolling();
      } else if (data.model_error) {
        setStatus("having trouble starting — please try again shortly", "status-offline");
        stopHealthPolling();
      } else if (data.model_loading) {
        setStatus("starting up (loading the model)…", "status-loading");
        startHealthPolling();
      } else {
        setStatus("online (model loads on first message)", "status-online");
        stopHealthPolling();
      }
    } catch (err) {
      setStatus("offline — check backend", "status-offline");
      showError(`Can't reach Rupsaa backend at ${API_URL}. Is the API running?`);
    }
  }

  function startHealthPolling() {
    if (healthPollTimer) return;
    healthPollTimer = setInterval(checkHealth, 5000);
  }

  function stopHealthPolling() {
    if (!healthPollTimer) return;
    clearInterval(healthPollTimer);
    healthPollTimer = null;
  }

  function updateCharCounter() {
    const len = inputEl.value.length;
    if (len < CHAR_WARN_THRESHOLD) {
      charCounter.hidden = true;
      return;
    }
    charCounter.hidden = false;
    charCounter.textContent = `${len}/${MAX_CHARS}`;
    charCounter.classList.toggle("at-limit", len >= MAX_CHARS);
    charCounter.classList.toggle("near-limit", len < MAX_CHARS);
  }

  function startRateLimitCountdown(seconds) {
    rateLimitedUntil = Date.now() + seconds * 1000;
    sendBtn.disabled = true;
    if (countdownTimer) clearInterval(countdownTimer);
    const tick = () => {
      const remaining = Math.ceil((rateLimitedUntil - Date.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(countdownTimer);
        countdownTimer = null;
        rateLimitedUntil = 0;
        sendBtn.disabled = false;
        clearError();
        return;
      }
      showError(`Too many messages — please wait ${remaining}s and try again.`);
    };
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isSending || rateLimitedUntil > Date.now()) return;

    clearError();
    hideWelcome();
    appendBubble("user", text);
    inputEl.value = "";
    autoResize();
    updateCharCounter();

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

      if (res.status === 429) {
        const retryAfter = parseInt(res.headers.get("Retry-After"), 10);
        removeTypingIndicator();
        if (!inputEl.value.trim()) {
          inputEl.value = text;
          autoResize();
          updateCharCounter();
        }
        startRateLimitCountdown(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 15);
        return;
      }

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
      // Restore the failed message so the user can just hit send again — but only if they
      // haven't already started typing something new in the meantime.
      if (!inputEl.value.trim()) {
        inputEl.value = text;
        autoResize();
        updateCharCounter();
      }
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
      if (rateLimitedUntil <= Date.now()) sendBtn.disabled = false;
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
    [...messagesEl.children].forEach((child) => {
      if (child !== welcomeEl) child.remove();
    });
    welcomeEl.hidden = false;
    clearError();
    inputEl.focus();
  }

  sendBtn.addEventListener("click", sendMessage);
  resetBtn.addEventListener("click", resetConversation);
  inputEl.addEventListener("input", () => {
    autoResize();
    updateCharCounter();
  });
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  suggestionsEl.addEventListener("click", (e) => {
    const chip = e.target.closest(".suggestion-chip");
    if (!chip) return;
    inputEl.value = chip.textContent;
    sendMessage();
  });

  checkHealth();
  inputEl.focus();
})();
