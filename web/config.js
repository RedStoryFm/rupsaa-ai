// Backend URL configuration for the Rupsaa web chat.
// Do NOT hard-code localhost inside index.html/app.js — edit this file (or
// override window.RUPSAA_API_URL before this script loads) to point at
// whichever FastAPI backend you're running against.
window.RUPSAA_CONFIG = {
  apiUrl: window.RUPSAA_API_URL || "http://localhost:8000",
};
