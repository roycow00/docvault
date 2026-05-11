// docvault — edit / new ingest form
(() => {
  const params = new URLSearchParams(location.search);
  const sha = params.get("sha");
  const src = params.get("src");
  const draftId = params.get("draft");
  const lockMode = params.get("lockmode");  // "reference" | "move" | null
  const detailsMode = params.get("details") === "1";  // read-only view

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
  const elEditThis = $("edit-this");
  const elCancel = $("cancel");
  const elSuggested = $("suggested-tags");
  const elSuggestAi = $("suggest-ai");
  const elImportant = $("important");
  const elImportantHint = $("important-hint");
  const elOpenFile = $("open-file");
  const elShowFolder = $("show-folder");
  const elDeleteSource = $("delete-source");

  let mode = "create";   // "create" | "edit-existing" | "create-from-draft"
  let existingDoc = null;
  // Snapshot of the form's "clean" state, captured at the end of init().
  // Compared against the current values on beforeunload to decide whether
  // to warn about unsaved changes.
  let initialSnapshot = null;
  let bypassUnloadGuard = false;

  function snapshotForm() {
    return JSON.stringify({
      title: elTitle.value,
      intro: elIntro.value,
      tags: elTags.value,
      important: elImportant.checked,
      mode: elModeMove.checked ? "move" : (elModeRef.checked ? "reference" : ""),
    });
  }
  function isDirty() {
    return initialSnapshot !== null && snapshotForm() !== initialSnapshot;
  }
  function setDocTitle(text) {
    document.title = text ? `${text} — docvault` : "docvault";
  }

  function setBanner(text, kind = "info") {
    elBanner.className = `banner ${kind}`;
    elBanner.textContent = text;
    elBanner.classList.remove("hidden");
  }

  function escHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function fmtSize(b) {
    if (b == null) return "—";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
    return (b / 1073741824).toFixed(1) + " GB";
  }

  function fmtIsoDate(s) {
    // Strip the time-of-day for the user-facing dates; we only really care
    // about the day. Leave non-ISO strings alone so we don't accidentally
    // truncate something we don't recognize.
    if (typeof s !== "string") return String(s ?? "");
    const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : s;
  }

  function renderDetailsView(d) {
    const el = document.getElementById("details-view");

    const star = d.important
      ? '<span class="star" title="Marked important">⭐</span>'
      : "";
    const tagsHtml = (d.tags && d.tags.length)
      ? d.tags.map(t => `<span class="tag">${escHtml(t)}</span>`).join(" ")
      : '<span class="empty-value">No tags</span>';
    const introHtml = (d.intro && d.intro.trim())
      ? escHtml(d.intro)
      : '<span class="empty-value">No intro provided.</span>';
    const storageHtml = d.location.type === "vault"
      ? "Managed in vault"
      : `External reference${d.location.source ? ` <span class="muted">(${escHtml(d.location.source)})</span>` : ""}`;

    el.innerHTML = `
      <header class="details-hero">
        <h2 class="details-title">${star}<span>${escHtml(d.title || d.original_filename)}</span></h2>
        <p class="details-intro">${introHtml}</p>
        <div class="details-tags-row">${tagsHtml}</div>
      </header>

      <dl class="details-meta">
        <dt>Storage</dt>           <dd>${storageHtml}</dd>
        <dt>File path</dt>         <dd><code>${escHtml(d.location.resolved)}</code></dd>
        <dt>Original filename</dt> <dd>${escHtml(d.original_filename)}</dd>
        <dt>Type</dt>              <dd><code>${escHtml(d.mime)}</code></dd>
        <dt>Size</dt>              <dd>${fmtSize(d.size)}</dd>
        <dt>File created</dt>      <dd>${escHtml(fmtIsoDate(d.file_created))}</dd>
        <dt>Ingested</dt>          <dd>${escHtml(fmtIsoDate(d.ingested))}</dd>
      </dl>

      <details class="details-extras">
        <summary>SHA-256</summary>
        <code class="sha-block">${escHtml(d.sha256)}</code>
      </details>
    `;
    el.classList.remove("hidden");
  }

  function applyReadonly() {
    // Hide the editable form entirely in details mode and render a
    // definition-list view of the same data instead. The buttons row stays
    // visible so Open file / Show in folder / Edit this record are
    // reachable.
    const form = document.getElementById("edit-form");
    if (form) form.classList.add("hidden");
    if (existingDoc) renderDetailsView(existingDoc);
    elSave.classList.add("hidden");
    elEditThis.classList.remove("hidden");
    document.body.classList.add("readonly-mode");
  }

  function csv(tags) { return (tags || []).join(", "); }
  function parseTags(s) {
    return s.split(",").map(t => t.trim()).filter(Boolean);
  }

  function escAttr(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Fallback shown immediately while the API resolves; replaced when the
  // /api/suggested-tags response (existing-vault tags by frequency, plus
  // config-defined extras) comes back.
  const FALLBACK_SUGGESTED = ["Immigration", "House", "Shopping", "School", "Finance", "Tax"];

  function paintSuggested(tags) {
    elSuggested.innerHTML = tags
      .map(t => `<span class="suggested-chip" data-tag="${escAttr(t)}">${escAttr(t)}</span>`)
      .join("");
  }

  async function renderSuggested() {
    paintSuggested(FALLBACK_SUGGESTED);
    elSuggested.addEventListener("click", ev => {
      const chip = ev.target.closest("[data-tag]");
      if (!chip) return;
      const tag = chip.dataset.tag;
      const cur = parseTags(elTags.value);
      if (!cur.includes(tag)) cur.push(tag);
      elTags.value = cur.join(", ");
      // The form just got dirtier — but only if the user is editing.
    });
    try {
      const r = await fetch("/api/suggested-tags");
      if (r.ok) {
        const data = await r.json();
        if (Array.isArray(data.suggested) && data.suggested.length) {
          paintSuggested(data.suggested);
        }
      }
    } catch (_) {
      // keep fallback
    }
  }

  function wireBackLink() {
    // If we got here from the ingest-ai timeline, retarget the topbar back
    // link so the user can return to it (the timeline has the LLM's "what
    // was sent / what came back" panels and per-phase timing). Use
    // history.back() so we return to the still-rendered page rather than
    // a fresh /static/ingest-ai.html?src=... that would re-trigger ingest.
    const back = document.querySelector("header.topbar a.back");
    if (!back) return;
    if (document.referrer && document.referrer.includes("/static/ingest-ai.html")) {
      back.textContent = "← back to ingest log";
      back.href = "#";
      back.addEventListener("click", ev => {
        ev.preventDefault();
        history.back();
      });
    }
  }

  async function init() {
    renderSuggested();
    wireBackLink();
    if (sha) {
      mode = "edit-existing";
      const r = await fetch(`/api/docs/${encodeURIComponent(sha)}`);
      if (!r.ok) {
        setBanner("could not load document: " + await r.text(), "error");
        return;
      }
      existingDoc = await r.json();
      elPageTitle.textContent = detailsMode ? "Document details" : "Edit metadata";
      setDocTitle(detailsMode
        ? existingDoc.title || "Document details"
        : `Edit · ${existingDoc.title || existingDoc.original_filename}`);
      elTitle.value = existingDoc.title;
      elIntro.value = existingDoc.intro;
      elTags.value = csv(existingDoc.tags);
      elSrc.textContent = existingDoc.location.resolved;
      elImportant.checked = !!existingDoc.important;
      // For external/reference records the file isn't in the vault, so the
      // flag is metadata-only. Be honest about that in the hint.
      if (existingDoc.location.type !== "vault") {
        elImportantHint.textContent =
          "Reference record — flag is recorded in metadata; the file stays where it is.";
      }
      // Always-available shortcuts for any existing record.
      elOpenFile.classList.remove("hidden");
      elShowFolder.classList.remove("hidden");
      if (detailsMode) applyReadonly();

      // Storage radio is informational on existing records (immutable through PUT)
      elStorageFs.querySelector("legend").textContent = `Storage (${existingDoc.location.type})`;
      [...elStorageFs.querySelectorAll("input")].forEach(i => i.disabled = true);
      if (existingDoc.location.type === "vault") elModeMove.checked = true;
      else elModeRef.checked = true;
      elStorageHint.textContent = existingDoc.location.source === "onedrive_personal_vault"
        ? "🔒 Stored in OneDrive Personal Vault."
        : (existingDoc.location.type === "external" ? "External reference." : "Managed in vault.");

      if (existingDoc.location.type === "external") {
        elMoveToVault.classList.remove("hidden");
      }
    } else if (src) {
      mode = "create";
      elPageTitle.textContent = "Ingest document";
      setDocTitle("Ingest document");
      elSrc.textContent = src;
      elTitle.value = src.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");

      // Default mode based on path
      const looksProtected = /[\\/]onedrive[\\/]personal vault[\\/]/i.test(src);
      if (looksProtected) {
        elModeRef.checked = true;
        elStorageHint.textContent = "🔒 OneDrive Personal Vault detected — defaulting to Reference in place.";
      } else {
        elModeMove.checked = true;
        elStorageHint.textContent = "Move into vault is the default for files outside protected locations.";
      }
      // Pre-save: surface "Open file" so the user can sanity-check the source,
      // and "Delete instead" so they can bail out without ingesting.
      elOpenFile.classList.remove("hidden");
      elDeleteSource.classList.remove("hidden");
    } else if (draftId) {
      mode = "create-from-draft";
      const r = await fetch(`/api/draft/${encodeURIComponent(draftId)}`);
      if (!r.ok) {
        setBanner("could not load draft: " + await r.text(), "error");
        return;
      }
      const draft = await r.json();

      // Duplicate sha256 — show the popup the user asked for and jump to the
      // existing record's read-only details view. We do this before rendering
      // anything so the user never sees an AI-draft form for a file that's
      // already in the vault.
      if (draft.duplicate_of_sha256) {
        docvault.flash("Duplicate detected — opened existing record.", "info");
        bypassUnloadGuard = true;
        location.replace(`/static/edit.html?sha=${encodeURIComponent(draft.duplicate_of_sha256)}&details=1`);
        return;
      }

      elPageTitle.textContent = "Review AI-suggested metadata";
      setDocTitle(`Review · ${draft.title || draft.src_path.split(/[\\/]/).pop()}`);
      elSrc.textContent = draft.src_path;
      elTitle.value = draft.title;
      elIntro.value = draft.intro;
      elTags.value = csv(draft.tags);
      elImportant.checked = !!draft.important;
      if (draft.suggested_mode === "reference") elModeRef.checked = true;
      else elModeMove.checked = true;

      if (draft.error) {
        setBanner("AI extraction failed — fill manually. Detail: " + draft.error, "error");
      } else if (draft.note) {
        setBanner("Note from extractor: " + draft.note, "info");
      } else {
        setBanner("Suggestions are AI-drafted — please review.", "info");
      }
      // Pre-save: surface "Open file" so the user can cross-reference the
      // AI output against the actual document, and "Delete instead" so they
      // can bail out without ingesting.
      elOpenFile.classList.remove("hidden");
      elDeleteSource.classList.remove("hidden");
      // Stash draft id for save
      window._draftId = draftId;
    } else {
      setBanner("No source path or sha provided.", "error");
    }

    // If the launcher locked the storage mode (e.g. "Ingest in-place" verb),
    // apply that override last so it wins over the auto-detected default,
    // then disable the radios so the user can't accidentally change it.
    if (lockMode === "reference" || lockMode === "move") {
      if (lockMode === "reference") elModeRef.checked = true;
      else elModeMove.checked = true;
      [elModeMove, elModeRef].forEach(i => i.disabled = true);
      elStorageHint.textContent =
        lockMode === "reference"
          ? "🔒 Locked to in-place by the launcher — file will stay where it is."
          : "🔒 Locked to move-into-vault by the launcher.";
    }

    // Snapshot the form's clean state so beforeunload can warn on
    // discards. Skip in details (read-only) mode — there's nothing to
    // lose because nothing can change.
    if (!detailsMode) {
      initialSnapshot = snapshotForm();
    }
  }

  async function save() {
    const payload = {
      title: elTitle.value.trim(),
      intro: elIntro.value,
      tags: parseTags(elTags.value),
      important: elImportant.checked,
    };

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
      bypassUnloadGuard = true;
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
      setBanner("ingest failed: " + await r.text(), "error");
      return;
    }
    const out = await r.json();
    if (out.duplicate) {
      docvault.flash("Duplicate detected — opened existing record.", "info");
      bypassUnloadGuard = true;
      location.href = `/static/edit.html?sha=${encodeURIComponent(out.sha256)}&details=1`;
      return;
    }
    bypassUnloadGuard = true;
    location.href = `/static/index.html?highlight=${encodeURIComponent(out.sha256)}`;
  }

  function currentSrcPath() {
    // Returns the absolute path of the source file the form is editing,
    // or null if there isn't one (shouldn't happen — the button hides itself
    // in that case via init()).
    if (mode === "edit-existing" && existingDoc) return existingDoc.location.resolved;
    if (mode === "create-from-draft" && elSrc.textContent) return elSrc.textContent;
    if (mode === "create" && src) return src;
    return null;
  }

  elSuggestAi.addEventListener("click", async () => {
    const path = currentSrcPath();
    if (!path) {
      setBanner("Can't suggest: no source file path available.", "error");
      return;
    }
    elSuggestAi.disabled = true;
    const originalLabel = elSuggestAi.textContent;
    elSuggestAi.textContent = "thinking...";
    try {
      const r = await fetch("/api/extract/metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ src_path: path }),
      });
      if (!r.ok) {
        setBanner("Suggestion failed: " + await r.text(), "error");
        return;
      }
      const out = await r.json();
      if (out.error) {
        setBanner("LLM error: " + out.error, "error");
        // Still apply whatever we got (likely just the filename stem).
      }
      if (out.title) elTitle.value = out.title;
      if (out.intro) elIntro.value = out.intro;
      if (out.tags && out.tags.length) {
        // Merge with any tags the user has already entered, avoiding dupes.
        const existing = parseTags(elTags.value);
        const seen = new Set(existing.map(t => t.toLowerCase()));
        for (const t of out.tags) {
          if (!seen.has(t.toLowerCase())) {
            existing.push(t);
            seen.add(t.toLowerCase());
          }
        }
        elTags.value = existing.join(", ");
      }
      if (!out.error) {
        setBanner("AI suggestions applied. Review and edit before saving.", "info");
      }
    } catch (e) {
      setBanner("Suggestion request failed: " + e.message, "error");
    } finally {
      elSuggestAi.disabled = false;
      elSuggestAi.textContent = originalLabel;
    }
  });

  // Browser beforeunload guard: prompt if the form has unsaved changes.
  // Save/dupe-redirect paths set bypassUnloadGuard=true before navigating
  // so the user isn't double-prompted on intentional flows.
  window.addEventListener("beforeunload", ev => {
    if (bypassUnloadGuard) return;
    if (isDirty()) {
      ev.preventDefault();
      ev.returnValue = "";  // some browsers require this
    }
  });

  elSave.addEventListener("click", save);
  elCancel.addEventListener("click", () => {
    if (isDirty() && !confirm("Discard your changes?")) return;
    bypassUnloadGuard = true;
    history.length > 1 ? history.back() : (location.href = "/static/index.html");
  });

  elEditThis.addEventListener("click", () => {
    if (!existingDoc) return;
    bypassUnloadGuard = true;
    location.href = `/static/edit.html?sha=${encodeURIComponent(existingDoc.sha256)}`;
  });

  elOpenFile.addEventListener("click", async () => {
    // Existing record: open via the sha-based endpoint (resolves the file's
    // vault location). Pre-save (create / create-from-draft): the file isn't
    // in the vault yet — open the raw source path.
    let r;
    if (existingDoc) {
      r = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sha256: existingDoc.sha256 }),
      });
    } else {
      const path = currentSrcPath();
      if (!path) { setBanner("No source path available.", "error"); return; }
      r = await fetch("/api/source/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ src_path: path }),
      });
    }
    if (!r.ok) {
      setBanner("Could not open file: " + await r.text(), "error");
    }
  });

  elDeleteSource.addEventListener("click", async () => {
    const path = currentSrcPath();
    if (!path) { setBanner("No source path available.", "error"); return; }
    const name = path.split(/[\\/]/).pop();
    if (!confirm(
      `Delete this file instead of ingesting it?\n\n` +
      `  ${path}\n\n` +
      `The file will be permanently removed. This cannot be undone.`
    )) return;
    const r = await fetch("/api/source/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src_path: path }),
    });
    if (!r.ok) {
      setBanner("Delete failed: " + await r.text(), "error");
      return;
    }
    bypassUnloadGuard = true;  // suppress the unsaved-changes prompt
    docvault.flash(`Deleted "${name}".`, "success");
    location.href = "/static/index.html";
  });

  elShowFolder.addEventListener("click", async () => {
    if (!existingDoc) return;
    const r = await fetch("/api/show", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sha256: existingDoc.sha256 }),
    });
    if (!r.ok) {
      setBanner("Could not reveal in folder: " + await r.text(), "error");
    }
  });
  elMoveToVault.addEventListener("click", async () => {
    if (!existingDoc) return;
    const r = await fetch(`/api/docs/${encodeURIComponent(existingDoc.sha256)}/move-to-vault`, { method: "POST" });
    if (!r.ok) {
      setBanner("move-to-vault failed: " + await r.text(), "error");
      return;
    }
    const updated = await r.json();
    bypassUnloadGuard = true;
    location.href = `/static/index.html?highlight=${encodeURIComponent(updated.sha256)}`;
  });

  init();
})();
