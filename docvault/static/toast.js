// docvault — toast notifications.
//
// Non-blocking message banners that slide in from the top-right and fade
// out automatically. Replaces alert() for transient notifications (errors,
// dupe-detected, "couldn't open file"), but NOT for confirm() — destructive
// actions still need an explicit yes/no.
//
// Cross-page flash: stash a message in sessionStorage under
// "docvault.flash" before navigating; the destination page picks it up on
// load and shows the toast. This is how the "Duplicate detected" notice
// survives the redirect from save → existing-record details.
(() => {
  const FLASH_KEY = "docvault.flash";

  function ensureContainer() {
    let c = document.getElementById("toast-container");
    if (c) return c;
    c = document.createElement("div");
    c.id = "toast-container";
    c.className = "toast-container";
    c.setAttribute("role", "status");
    c.setAttribute("aria-live", "polite");
    document.body.appendChild(c);
    return c;
  }

  function show(message, kind = "info", duration = 4500) {
    const c = ensureContainer();
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`;
    t.textContent = message;
    // Click dismisses early.
    t.addEventListener("click", () => dismiss(t));
    c.appendChild(t);
    // Force layout so the slide-in transition fires.
    void t.offsetHeight;
    t.classList.add("toast-in");
    if (duration > 0) {
      setTimeout(() => dismiss(t), duration);
    }
    return t;
  }

  function dismiss(t) {
    if (!t.parentNode) return;
    t.classList.remove("toast-in");
    t.classList.add("toast-out");
    setTimeout(() => { if (t.parentNode) t.parentNode.removeChild(t); }, 250);
  }

  function flash(message, kind = "info") {
    try {
      sessionStorage.setItem(FLASH_KEY, JSON.stringify({ message, kind }));
    } catch (_) { /* private browsing? swallow */ }
  }

  function consumeFlash() {
    try {
      const raw = sessionStorage.getItem(FLASH_KEY);
      if (!raw) return;
      sessionStorage.removeItem(FLASH_KEY);
      const { message, kind } = JSON.parse(raw);
      if (message) show(message, kind || "info", 6000);
    } catch (_) { /* malformed — ignore */ }
  }

  window.docvault = window.docvault || {};
  window.docvault.toast = show;
  window.docvault.flash = flash;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", consumeFlash);
  } else {
    consumeFlash();
  }
})();
