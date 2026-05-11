// docvault — AI ingest progress page.
// Streams /api/ingest/ai/stream (NDJSON), updates the elapsed clock, the
// timeline, and the "what was sent" / "what came back" panels. Auto-redirects
// to the edit form on done, or to the existing record on duplicate.
(() => {
  const params = new URLSearchParams(location.search);
  const src = params.get("src");
  const lockMode = params.get("lockmode");

  const $ = id => document.getElementById(id);
  const elFile = $("filename");
  const elElapsed = $("elapsed-num");
  const elPhase = $("phase");
  const elTimeline = $("timeline");
  const elBanner = $("banner");
  const elHero = document.querySelector(".hero");
  const elDecisionSection = $("decision-section");
  const elDecision = $("decision");
  const elTextPreviewWrap = $("text-preview-wrap");
  const elTextPreview = $("text-preview");
  const elVisionInfo = $("vision-info");
  const elVisionDetail = $("vision-detail");
  const elResultSection = $("result-section");
  const elRTitle = $("r-title");
  const elRTags = $("r-tags");
  const elRIntro = $("r-intro");

  function basename(p) {
    if (!p) return "";
    return p.replace(/\\/g, "/").split("/").pop();
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function setBanner(msg, kind) {
    elBanner.className = `banner ${kind || "info"}`;
    elBanner.textContent = msg;
    elBanner.classList.remove("hidden");
  }

  if (!src) {
    setBanner("No ?src= file path provided.", "error");
    return;
  }

  elFile.textContent = basename(src) + " — " + src;

  // Live elapsed-time clock. The server also sends `t` per event but the
  // local clock keeps the big counter ticking smoothly between events.
  const t0 = performance.now();
  let stopClock = false;
  function tick() {
    if (stopClock) return;
    const t = (performance.now() - t0) / 1000;
    elElapsed.textContent = Math.floor(t);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  // Timeline rendering: one <li> per phase. We append the closing message
  // to the previous active item so events read top-to-bottom.
  let activeLi = null;
  function timelineMark(state) {
    if (!activeLi) return;
    activeLi.classList.remove("active");
    activeLi.classList.add(state);
  }
  function timelinePush(t, label, extraHtml) {
    timelineMark("done");
    const li = document.createElement("li");
    li.classList.add("active");
    li.innerHTML =
      `<span class="t">${t.toFixed(2)}s</span>` +
      `<span class="msg">${esc(label)}</span>` +
      (extraHtml ? `<span class="extra">${extraHtml}</span>` : "");
    elTimeline.appendChild(li);
    activeLi = li;
  }
  function timelineAddExtra(html) {
    if (!activeLi) return;
    let extra = activeLi.querySelector(".extra");
    if (!extra) {
      extra = document.createElement("span");
      extra.className = "extra";
      activeLi.appendChild(extra);
    }
    extra.innerHTML = html;
  }

  function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1048576).toFixed(1)} MB`;
  }

  function showDecision(kind, why) {
    elDecisionSection.classList.remove("hidden");
    elDecision.innerHTML =
      `<div class="which ${kind === "vision" ? "vision" : "text"}">` +
      (kind === "vision" ? "🖼  Sending images to the model" : "📄 Sending text to the model") +
      `</div>` +
      `<div class="why">${esc(why)}</div>`;
  }

  function showResult(title, intro, tags) {
    elResultSection.classList.remove("hidden");
    elRTitle.textContent = title || "(empty)";
    elRTags.innerHTML = (tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(" ") || "<em>(none)</em>";
    elRIntro.textContent = intro || "(empty)";
  }

  function finalize(state, message) {
    stopClock = true;
    timelineMark(state);
    elHero.classList.add(state);
    elPhase.textContent = message;
  }

  function showContinue(url) {
    const wrap = document.createElement("div");
    wrap.className = "continue-wrap";
    const btn = document.createElement("a");
    btn.href = url;
    btn.className = "continue-btn";
    btn.textContent = "Continue to finalize →";
    wrap.appendChild(btn);
    elHero.appendChild(wrap);
  }

  async function run() {
    let r;
    try {
      r = await fetch("/api/ingest/ai/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ src_path: src }),
      });
    } catch (e) {
      finalize("error", "request failed");
      setBanner("Could not reach the server: " + e.message, "error");
      return;
    }
    if (!r.ok) {
      finalize("error", "server error");
      setBanner("Server returned " + r.status + ": " + (await r.text()), "error");
      return;
    }

    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        let evt;
        try { evt = JSON.parse(line); } catch { continue; }
        handle(evt);
      }
    }
  }

  function handle(evt) {
    const t = evt.t || 0;
    switch (evt.event) {
      case "start":
        elPhase.textContent = "starting…";
        break;

      case "phase":
        elPhase.textContent = evt.message || evt.phase;
        timelinePush(t, evt.message || evt.phase);
        break;

      case "hash_done":
        timelineAddExtra(`sha256: <code>${esc(evt.sha256.slice(0, 16))}…</code>`);
        break;

      case "extract_text_done": {
        const note = evt.note ? ` — ${esc(evt.note)}` : "";
        const trunc = evt.truncated ? " (truncated)" : "";
        timelineAddExtra(
          `${evt.chars.toLocaleString()} chars, mime <code>${esc(evt.mime)}</code>${trunc}${note}`
        );
        if (evt.preview) {
          elTextPreview.textContent = evt.preview + (evt.chars > evt.preview.length ? "\n\n…" : "");
          elTextPreviewWrap.classList.remove("hidden");
        }
        break;
      }

      case "decision":
        showDecision("text", evt.reason);
        timelineAddExtra(`text path — ${esc(evt.reason)}`);
        break;

      case "rasterize_done": {
        const summary = `${evt.page_count} page(s), ${fmtBytes(evt.bytes_total)} total`;
        timelineAddExtra(summary);
        showDecision("vision",
          `extracted text was empty — sending ${evt.page_count} rasterized page(s) (${fmtBytes(evt.bytes_total)}) instead`);
        elVisionInfo.classList.remove("hidden");
        elVisionDetail.innerHTML = `<p>${esc(summary)}. Note: docvault doesn't run OCR — the LLM does its own visual reading internally. The "Model output" panel below is what the model came back with.</p>`;
        break;
      }

      case "llm_call_done":
        timelineAddExtra(`title: <em>${esc(evt.title || "(empty)")}</em>`);
        showResult(evt.title, evt.intro, evt.tags);
        break;

      case "llm_error":
        timelineMark("error");
        setBanner("LLM call failed: " + evt.error + " — falling through to the manual edit form.", "error");
        break;

      case "duplicate":
        finalize("done", "duplicate detected");
        docvault.flash(
          `Duplicate detected — opened existing record "${evt.existing_title || "(untitled)"}".`,
          "info"
        );
        location.replace("/static/edit.html?sha=" + encodeURIComponent(evt.existing_sha256) + "&details=1");
        break;

      case "fatal":
        finalize("error", "ingest aborted");
        setBanner(evt.detail || "fatal error", "error");
        break;

      case "done": {
        finalize("done", `done in ${Math.floor(t)}s`);
        let url = "/static/edit.html?draft=" + encodeURIComponent(evt.draft_id);
        if (lockMode === "reference" || lockMode === "move") {
          url += "&lockmode=" + encodeURIComponent(lockMode);
        }
        // Don't auto-redirect: leave the timeline visible so the user can
        // review what the model actually did. `location.href` (not replace)
        // means the back button returns to this page from the edit form.
        showContinue(url);
        break;
      }

      default:
        // ignore unknown events
        break;
    }
  }

  run();
})();
