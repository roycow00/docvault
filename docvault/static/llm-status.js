// docvault — LLM connection status pill.
//
// Polls /api/llm/status on page load and every 30s. Renders into
// #llm-status if present. Quick (<2s timeout server-side), so safe to
// run on every page.
(() => {
  const el = document.getElementById("llm-status");
  if (!el) return;

  async function refresh() {
    try {
      const r = await fetch("/api/llm/status", { cache: "no-store" });
      if (!r.ok) {
        el.className = "llm-status bad";
        el.textContent = `LLM error (${r.status})`;
        el.title = `/api/llm/status returned HTTP ${r.status}`;
        return;
      }
      const s = await r.json();
      const where = s.base_url ? ` @ ${s.base_url}` : "";
      const pretty = `${s.provider}: ${s.model}`;
      if (s.connected) {
        el.className = "llm-status ok";
        el.textContent = pretty;
        el.title = `connected — ${s.detail}${where}`;
      } else {
        el.className = "llm-status bad";
        el.textContent = pretty;
        el.title = `disconnected — ${s.detail}${where}`;
      }
    } catch (e) {
      el.className = "llm-status bad";
      el.textContent = "LLM status: server unreachable";
      el.title = String(e);
    }
  }

  refresh();
  setInterval(refresh, 30000);
})();
