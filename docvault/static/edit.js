// docvault — edit / new ingest form
(() => {
  const params = new URLSearchParams(location.search);
  const sha = params.get("sha");
  const src = params.get("src");
  const draftId = params.get("draft");
  const lockMode = params.get("lockmode");  // "reference" | "move" | null

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
  const elSuggestAi = $("suggest-ai");

  let mode = "create";   // "create" | "edit-existing"
  let existingDoc = null;

  function setBanner(text, kind = "info") {
    elBanner.className = `banner ${kind}`;
    elBanner.textContent = text;
    elBanner.classList.remove("hidden");
  }

  function csv(tags) { return (tags || []).join(", "); }
  function parseTags(s) {
    return s.split(",").map(t => t.trim()).filter(Boolean);
  }

  function renderSuggested() {
    // Hardcoded suggestions for now; will be served from API later.
    const SUGGESTED = ["Immigration", "House", "Shopping", "School", "Finance", "Tax"];
    elSuggested.innerHTML = SUGGESTED.map(t => `<span class="suggested-chip" data-tag="${t}">${t}</span>`).join("");
    elSuggested.addEventListener("click", ev => {
      const chip = ev.target.closest("[data-tag]");
      if (!chip) return;
      const tag = chip.dataset.tag;
      const cur = parseTags(elTags.value);
      if (!cur.includes(tag)) cur.push(tag);
      elTags.value = cur.join(", ");
    });
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
    } else if (draftId) {
      mode = "create-from-draft";
      const r = await fetch(`/api/draft/${encodeURIComponent(draftId)}`);
      if (!r.ok) {
        setBanner("could not load draft: " + await r.text(), "error");
        return;
      }
      const draft = await r.json();

      // Duplicate sha256 — show the popup the user asked for and jump to the
      // existing record. We do this before rendering anything so the user
      // never sees an AI-draft form for a file that's already in the vault.
      if (draft.duplicate_of_sha256) {
        alert("Duplicate entry — this file is already in your vault.\n\nOpening the existing record.");
        location.replace(`/static/edit.html?sha=${encodeURIComponent(draft.duplicate_of_sha256)}`);
        return;
      }

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
        setBanner("Suggestions are AI-drafted — please review.", "info");
      }
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
  }

  async function save() {
    const payload = {
      title: elTitle.value.trim(),
      intro: elIntro.value,
      tags: parseTags(elTags.value),
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
      alert("Duplicate entry — this file is already in your vault.\n\nOpening the existing record.");
      location.href = `/static/edit.html?sha=${encodeURIComponent(out.sha256)}`;
      return;
    }
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

  elSave.addEventListener("click", save);
  elCancel.addEventListener("click", () => { history.length > 1 ? history.back() : (location.href = "/static/index.html"); });
  elMoveToVault.addEventListener("click", async () => {
    if (!existingDoc) return;
    const r = await fetch(`/api/docs/${encodeURIComponent(existingDoc.sha256)}/move-to-vault`, { method: "POST" });
    if (!r.ok) {
      setBanner("move-to-vault failed: " + await r.text(), "error");
      return;
    }
    const updated = await r.json();
    location.href = `/static/index.html?highlight=${encodeURIComponent(updated.sha256)}`;
  });

  init();
})();
