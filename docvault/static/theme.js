// docvault — theme toggle.
//
// Three-state preference: "auto" (follows OS prefers-color-scheme), "light",
// or "dark". The choice is persisted in localStorage under "docvault.theme"
// and applied to <html> via data-theme so app.css's CSS variables flip.
//
// Pages opt in by either:
//   1. Including a button with id="theme-toggle" in the topbar, or
//   2. Letting this script auto-inject one just before #llm-status.
(() => {
  const KEY = "docvault.theme";
  const order = ["auto", "light", "dark"];
  const labels = { auto: "🌓 Auto", light: "☀ Light", dark: "🌙 Dark" };

  function read() {
    const v = localStorage.getItem(KEY);
    return order.includes(v) ? v : "auto";
  }

  function apply(pref) {
    const root = document.documentElement;
    if (pref === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", pref);
  }

  // Apply the saved preference as early as possible.
  apply(read());

  function ensureButton() {
    let btn = document.getElementById("theme-toggle");
    if (btn) return btn;
    const llm = document.getElementById("llm-status");
    if (!llm || !llm.parentNode) return null;
    btn = document.createElement("button");
    btn.id = "theme-toggle";
    btn.type = "button";
    btn.className = "theme-toggle";
    btn.title = "Toggle light / dark / auto theme";
    llm.parentNode.insertBefore(btn, llm);
    return btn;
  }

  function refreshLabel(btn, pref) {
    btn.textContent = labels[pref] || labels.auto;
    btn.setAttribute("aria-label", `Theme: ${pref}`);
  }

  function init() {
    const btn = ensureButton();
    if (!btn) return;
    refreshLabel(btn, read());
    btn.addEventListener("click", () => {
      const cur = read();
      const next = order[(order.indexOf(cur) + 1) % order.length];
      localStorage.setItem(KEY, next);
      apply(next);
      refreshLabel(btn, next);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
