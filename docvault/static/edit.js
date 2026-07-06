// docvault — edit / new ingest form
(() => {
  const params = new URLSearchParams(location.search);
  const sha = params.get("sha");
  const src = params.get("src");
  const draftId = params.get("draft");
  const isDupRedirect = params.get("dup") === "1";

  const $ = id => document.getElementById(id);
  const elTitle = $("title");
  const elIntro = $("intro");
  const elTags = $("tags");
  const elSrc = $("source-path");
  const elBanner = $("banner");
  const elPageTitle = $("page-title");
  const elModeMove = document.querySelector('input[name="mode"][value="move"]');
  const elModeRef = document.querySelector('input[name="mode"][value="reference"]');
  const elStorageHint = $("storage-hint");
  const elStorageFs = $("storage-fs");
  const elMoveToVault = $("move-to-vault");
  const elSave = $("save");
  const elCancel = $("cancel");
  const elSuggested = $("suggested-tags");
  const elDetails = $("doc-details");

  let mode = "create";   // "create" | "create-from-draft" | "edit-existing"
  let existingDoc = null;
  let saving = false;

  function setBanner(text, kind = "info") {
    elBanner.className = `banner ${kind}`;
    elBanner.textContent = text;
    elBanner.classList.remove("hidden");
  }

  function csv(tags) { return (tags || []).join(", "); }
  function parseTags(s) {
    return s.split(",").map(t => t.trim()).filter(Boolean);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function fmtSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
    if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + " MB";
    return (b / 1024 / 1024 / 1024).toFixed(1) + " GB";
  }

  const FALLBACK_TAGS = ["Immigration", "House", "Shopping", "School", "Finance", "Tax"];

  async function renderSuggested() {
    let tags = FALLBACK_TAGS;
    try {
      const cfg = await (await fetch("/api/config")).json();
      if (cfg.suggested_tags && cfg.suggested_tags.length) tags = cfg.suggested_tags;
    } catch (e) { /* offline fallback */ }
    elSuggested.innerHTML = tags.map(t => `<span class="suggested-chip" data-tag="${esc(t)}">${esc(t)}</span>`).join("");
  }

  elSuggested.addEventListener("click", ev => {
    const chip = ev.target.closest("[data-tag]");
    if (!chip) return;
    const tag = chip.dataset.tag;
    const cur = parseTags(elTags.value);
    if (!cur.includes(tag)) cur.push(tag);
    elTags.value = cur.join(", ");
  });

  function renderDetails(doc) {
    const rows = [
      ["File", doc.original_filename],
      ["Size", fmtSize(doc.size)],
      ["Type", doc.mime],
      ["Created", doc.file_created.slice(0, 10)],
      ["Ingested", doc.ingested.slice(0, 10)],
      ["SHA-256", doc.sha256.slice(0, 16) + "…"],
    ];
    elDetails.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
    elDetails.classList.remove("hidden");
  }

  async function init() {
    renderSuggested();
    if (sha) {
      mode = "edit-existing";
      const r = await fetch(`/api/docs/${encodeURIComponent(sha)}`);
      if (!r.ok) {
        setBanner("could not load document: " + await r.text(), "error");
        return;
      }
      existingDoc = await r.json();
      elPageTitle.textContent = "Edit metadata";
      elTitle.value = existingDoc.title;
      elIntro.value = existingDoc.intro;
      elTags.value = csv(existingDoc.tags);
      elSrc.textContent = existingDoc.location.resolved;
      renderDetails(existingDoc);

      if (isDupRedirect) {
        setBanner("This file is already in docvault — you are editing the existing record. The duplicate copy was left untouched.", "info");
      }

      // Storage radio is informational on existing records (immutable through PUT)
      elStorageFs.querySelector("legend").textContent = `Storage (${existingDoc.location.type})`;
      [...elStorageFs.querySelectorAll("input")].forEach(i => i.disabled = true);
      if (existingDoc.location.type === "vault") elModeMove.checked = true;
      else elModeRef.checked = true;
      elStorageHint.textContent = existingDoc.location.source === "onedrive_personal_vault"
        ? "🔒 Stored in OneDrive Personal Vault."
        : (existingDoc.location.type === "external" ? "External reference — the file stays where it is." : "Managed in vault.");

      if (existingDoc.location.type === "external") {
        elMoveToVault.classList.remove("hidden");
      }
    } else if (src) {
      mode = "create";
      elPageTitle.textContent = "Ingest document";
      elSrc.textContent = src;
      elTitle.value = src.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");

      // Default mode based on path
      const looksProtected = /[\\/]onedrive[\\/]personal vault[\\/]/i.test(src);
      if (looksProtected) {
        elModeRef.checked = true;
        elStorageHint.textContent = "🔒 OneDrive Personal Vault detected — defaulting to Reference in place.";
      } else {
        elModeMove.checked = true;
        elStorageHint.textContent = "Move into vault copies the file, verifies the copy, then retires the original (undoable).";
      }
    } else if (draftId) {
      mode = "create-from-draft";
      const r = await fetch(`/api/draft/${encodeURIComponent(draftId)}`);
      if (!r.ok) {
        setBanner("could not load draft: " + await r.text(), "error");
        return;
      }
      const draft = await r.json();
      elPageTitle.textContent = "Review AI-suggested metadata";
      elSrc.textContent = draft.src_path;
      elTitle.value = draft.title;
      elIntro.value = draft.intro;
      elTags.value = csv(draft.tags);
      if (draft.suggested_mode === "reference") elModeRef.checked = true;
      else elModeMove.checked = true;

      if (draft.error) {
        setBanner("AI extraction failed — fill manually. Detail: " + draft.error, "error");
      } else if (draft.note) {
        setBanner("Note from extractor: " + draft.note, "info");
      } else {
        setBanner("Suggestions are AI-drafted — please review before saving.", "info");
      }
      window._draftId = draftId;
    } else {
      setBanner("No source path or sha provided.", "error");
    }
  }

  function setSaving(on) {
    saving = on;
    elSave.disabled = on;
    elSave.textContent = on ? "Saving…" : "Save";
  }

  async function save() {
    if (saving) return;
    const payload = {
      title: elTitle.value.trim(),
      intro: elIntro.value,
      tags: parseTags(elTags.value),
    };
    if (!payload.title) {
      setBanner("Title is required.", "error");
      elTitle.focus();
      return;
    }
    setSaving(true);
    try {
      if (mode === "edit-existing") {
        const r = await fetch(`/api/docs/${encodeURIComponent(existingDoc.sha256)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          setBanner("save failed: " + await r.text(), "error");
          return;
        }
        const updated = await r.json();
        location.href = `/static/index.html?highlight=${encodeURIComponent(updated.sha256)}`;
        return;
      }

      // create OR create-from-draft
      const ingestMode = elModeRef.checked ? "reference" : "move";
      let r;
      if (mode === "create-from-draft" && window._draftId) {
        r = await fetch("/api/ingest/finalize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ draft_id: window._draftId, metadata: payload, mode: ingestMode }),
        });
      } else {
        r = await fetch("/api/ingest/manual", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ src_path: src, metadata: payload, mode: ingestMode }),
        });
      }
      if (!r.ok) {
        const txt = await r.text();
        setBanner(
          r.status === 423
            ? "The file is locked or unreadable (OneDrive Personal Vault locked?). Unlock it and try again. Detail: " + txt
            : "ingest failed: " + txt,
          "error"
        );
        return;
      }
      const out = await r.json();
      if (out.duplicate) {
        // Hop to the existing record — let the user merge.
        location.href = `/static/edit.html?sha=${encodeURIComponent(out.sha256)}&dup=1`;
        return;
      }
      location.href = `/static/index.html?highlight=${encodeURIComponent(out.sha256)}`;
    } finally {
      setSaving(false);
    }
  }

  elSave.addEventListener("click", save);
  elCancel.addEventListener("click", () => { history.length > 1 ? history.back() : (location.href = "/static/index.html"); });
  document.addEventListener("keydown", ev => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); save(); }
  });
  elMoveToVault.addEventListener("click", async () => {
    if (!existingDoc) return;
    elMoveToVault.disabled = true;
    try {
      const r = await fetch(`/api/docs/${encodeURIComponent(existingDoc.sha256)}/move-to-vault`, { method: "POST" });
      if (!r.ok) {
        setBanner("move-to-vault failed: " + await r.text(), "error");
        return;
      }
      const updated = await r.json();
      location.href = `/static/index.html?highlight=${encodeURIComponent(updated.sha256)}`;
    } finally {
      elMoveToVault.disabled = false;
    }
  });

  init();
})();
