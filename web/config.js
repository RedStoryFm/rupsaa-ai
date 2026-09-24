// Backend URL configuration for the Rupsaa web chat.
//
// Default: relative "api" (no leading slash), proxied by web/dev_server.py
// to FastAPI on 127.0.0.1:8000. This must stay a *relative* path, not an
// absolute "/api" — Lightning Studio's forwarded-port proxy can front this
// server behind a path prefix (e.g. .../web-ui?port=5500), and an absolute
// path escapes that prefix straight to the wrong origin. A relative path
// resolves the same way this file itself was loaded (index.html references
// it as "config.js", not "/config.js"), so it always lands back on this
// same server regardless of what prefix fronts it.
//
// For a future production deployment where the API lives on a different
// origin, do NOT hard-code localhost inside index.html/app.js — instead
// override window.RUPSAA_API_URL (e.g. via a small inline <script> before
// this file loads, or by editing this file) to point at that API's full
// URL.
window.RUPSAA_CONFIG = {
  apiUrl: window.RUPSAA_API_URL || "api",
};
