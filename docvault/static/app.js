// docvault — table view
(() => {
  const rows = document.getElementById("rows");
  const emptyVault = document.getElementById("empty-vault");
  const emptySearch = document.getElementById("empty-search");
  const emptySearchQ = document.getElementById("empty-search-q");
  const search = document.getElementById("search");
  const count = document.getElementById("count");
  const dlg = document.getElementById("delete-dialog");
  const ingestDlg = document.getElementById("ingest-dialog");
  const ingestPathInput = document.getElementById("ingest-path");
  const ingestError = document.getElementById("ingest-error");
  const addIngestBtn = document.getElementById("add-ingest");
  const filterImportantBtn = document.getElementById("filter-important");

  let docs = [];
  let highlight = new URLSearchParams(location.search).get("highlight") || null;
  // Server returns newest-first; sortKey=null preserves that order until the
  // user clicks a header.
  let sortKey = null;
  let sortDir = 1;
  let importantOnly = false;

  async function load() {
    try {
      const r = await fetch("/api/docs");
      docs = await r.json();
    } catch (e) {
      docs = [];
    }
    render();
  }

  function fmtSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
    if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + " MB";
    return (b / 1024 / 1024 / 1024).toFixed(1) + " GB";
  }

  function fmtDate(iso) {
    return iso.slice(0, 10);
  }

  function badges(d) {
    const out = [];
    if (d.important) {
      out.push('<span class="badge important" title="Marked important">⭐</span>');
    }
    if (d.location.source === "onedrive_personal_vault") {
      out.push('<span class="badge lock" title="OneDrive Personal Vault — may require unlock">🔒</span>');
    }
    if (!d.accessible && d.location.source !== "onedrive_personal_vault") {
      out.push('<span class="badge missing" title="File missing or inaccessible">⚠️</span>');
    }
    return out.join("");
  }

  function rowHtml(d) {
    const tags = (d.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(" ");
    const detailsHref = `/static/edit.html?sha=${encodeURIComponent(d.sha256)}&details=1`;
    return `
      <tr data-sha="${d.sha256}">
        <td>
          <div class="title-cell">
            ${badges(d)}
            <a href="#" data-action="open" title="Open with default app">${esc(d.title || d.original_filename)}</a>
            <a href="${detailsHref}" class="details-btn" title="Details" aria-label="Details">
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4"/>
                <circle cx="8" cy="4.4" r="0.9" fill="currentColor"/>
                <rect x="7.1" y="6.7" width="1.8" height="5.4" rx="0.4" fill="currentColor"/>
              </svg>
            </a>
          </div>
        </td>
        <td>${tags}</td>
        <td>${fmtDate(d.ingested)}</td>
        <td>${fmtSize(d.size)}</td>
        <td class="actions">
          <a href="/static/edit.html?sha=${encodeURIComponent(d.sha256)}" title="Edit metadata">edit</a>
          <button data-action="show" title="Show file in Explorer">show</button>
          <button data-action="delete" class="danger" title="Delete this entry">del</button>
        </td>
      </tr>
    `;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function compareDocs(a, b) {
    let va = a[sortKey], vb = b[sortKey];
    if (sortKey === "title") {
      va = String(va || a.original_filename).toLowerCase();
      vb = String(vb || b.original_filename).toLowerCase();
    }
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  }

  function applyFilter() {
    const qRaw = search.value.trim();
    const q = qRaw.toLowerCase();
    let filtered = !q ? [...docs] : docs.filter(d => {
      const blob = (
        d.title + " " + (d.intro || "") + " " +
        (d.tags || []).join(" ") + " " + (d.original_filename || "")
      ).toLowerCase();
      return blob.includes(q);
    });
    if (importantOnly) filtered = filtered.filter(d => d.important);
    if (sortKey) filtered.sort(compareDocs);
    rows.innerHTML = filtered.map(rowHtml).join("");
    count.textContent = filtered.length === docs.length ? `${docs.length}` : `${filtered.length} / ${docs.length}`;

    // Distinct empty states: a fresh vault wants the "use the right-click
    // menu" guidance; a search that matched nothing wants the user to see
    // exactly what query they searched for so they can correct a typo.
    if (filtered.length === 0) {
      if (q || importantOnly) {
        emptyVault.classList.add("hidden");
        emptySearchQ.textContent = qRaw || (importantOnly ? "⭐ important" : "");
        emptySearch.classList.remove("hidden");
      } else {
        emptyVault.classList.remove("hidden");
        emptySearch.classList.add("hidden");
      }
    } else {
      emptyVault.classList.add("hidden");
      emptySearch.classList.add("hidden");
    }

    // Reflect the active query in the browser tab so users with multiple
    // tabs open can tell them apart.
    document.title = qRaw ? `${qRaw} — docvault` : "docvault";

    if (highlight) {
      const tr = rows.querySelector(`tr[data-sha="${CSS.escape(highlight)}"]`);
      if (tr) {
        tr.scrollIntoView({ block: "center" });
        tr.classList.add("just-saved");
      }
      highlight = null;
      // Drop ?highlight=… from the address bar — the cue has fired and
      // the param is just clutter that re-applies on reload.
      if (location.search) {
        history.replaceState(null, "", location.pathname);
      }
    }
  }

  function render() { applyFilter(); }

  search.addEventListener("input", applyFilter);
  search.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && search.value) {
      ev.stopPropagation();
      search.value = "";
      applyFilter();
    }
  });

  filterImportantBtn.addEventListener("click", () => {
    importantOnly = !importantOnly;
    filterImportantBtn.classList.toggle("active", importantOnly);
    filterImportantBtn.setAttribute("aria-pressed", String(importantOnly));
    applyFilter();
  });

  // Click a column header to sort; click again to flip direction. Title
  // starts ascending (A→Z), date and size start descending (newest/biggest).
  document.querySelectorAll("thead th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) {
        sortDir = -sortDir;
      } else {
        sortKey = key;
        sortDir = key === "title" ? 1 : -1;
      }
      document.querySelectorAll("thead th.sortable").forEach(el => {
        el.classList.toggle("sorted", el === th);
        el.classList.toggle("desc", el === th && sortDir === -1);
      });
      applyFilter();
    });
  });

  addIngestBtn.addEventListener("click", () => {
    ingestPathInput.value = "";
    ingestError.classList.add("hidden");
    ingestError.textContent = "";
    ingestDlg.showModal();
    // Focus *after* the dialog opens so Firefox doesn't drop focus.
    setTimeout(() => ingestPathInput.focus(), 0);
  });

  ingestDlg.addEventListener("close", () => {
    const action = ingestDlg.returnValue;
    if (!action || action === "cancel") return;
    const raw = ingestPathInput.value.trim();
    if (!raw) {
      docvault.toast("Path is empty.", "error", 3500);
      return;
    }
    // Strip enclosing quotes that "Copy as path" sometimes leaves on,
    // and normalise the few characters that would break a URL component
    // before encodeURIComponent gets to them.
    const path = raw.replace(/^"+|"+$/g, "");
    const enc = encodeURIComponent(path);
    if (action === "ai") {
      location.href = `/static/ingest-ai.html?src=${enc}`;
    } else if (action === "manual") {
      location.href = `/static/edit.html?src=${enc}`;
    } else if (action === "folder") {
      location.href = `/static/folder.html?root=${enc}`;
    }
  });

  rows.addEventListener("click", async ev => {
    // Click-to-filter: clicking a tag chip filters the table down to docs
    // that include that tag. Modifier-clicks (cmd/ctrl) ADD to the query;
    // a plain click replaces it.
    const tagEl = ev.target.closest(".tag");
    if (tagEl) {
      ev.preventDefault();
      const tag = tagEl.textContent.trim();
      search.value = (ev.metaKey || ev.ctrlKey) && search.value
        ? `${search.value} ${tag}`.trim()
        : tag;
      applyFilter();
      search.focus();
      return;
    }

    const target = ev.target.closest("[data-action]");
    if (!target) return;
    ev.preventDefault();
    const tr = target.closest("tr");
    const sha = tr.dataset.sha;
    const action = target.dataset.action;
    const doc = docs.find(d => d.sha256 === sha);
    if (!doc) return;

    if (action === "open") {
      const r = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sha256: sha }),
      });
      if (!r.ok) {
        const txt = await r.text();
        const hint = doc.location.source === "onedrive_personal_vault"
          ? " (OneDrive Personal Vault may need to be unlocked first)"
          : "";
        docvault.toast("Could not open: " + txt + hint, "error", 6000);
      }
    } else if (action === "show") {
      await fetch("/api/show", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sha256: sha }),
      });
    } else if (action === "delete") {
      openDeleteDialog(doc);
    }
  });

  function openDeleteDialog(doc) {
    document.getElementById("del-title").textContent = doc.title || doc.original_filename;
    document.getElementById("del-loc-type").textContent = doc.location.type === "vault" ? "in vault" : "external file (reference)";
    document.getElementById("del-path").textContent = doc.location.resolved;
    // The "entry and file" option behaves differently for references: the
    // file it moves to trash is the EXTERNAL original, not a vault copy.
    document.getElementById("del-file-hint").textContent = doc.location.type === "external"
      ? "Moves the EXTERNAL original file into the vault trash; recoverable for 90 days."
      : "Move both to trash; recoverable for 90 days.";
    dlg.returnValue = "";
    dlg.showModal();

    dlg.addEventListener("close", async function once() {
      dlg.removeEventListener("close", once);
      const action = dlg.returnValue;
      if (!action || action === "cancel") return;
      if (action === "entry_and_file_hard") {
        const name = doc.title || doc.original_filename;
        if (!confirm(
          `Permanently delete "${name}" and its file?\n\n` +
          `The file at:\n  ${doc.location.resolved}\n\n` +
          `will be unlinked immediately. There is NO trash recovery for this option.`
        )) return;
      }
      const r = await fetch(`/api/docs/${encodeURIComponent(doc.sha256)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!r.ok) {
        docvault.toast("Delete failed: " + await r.text(), "error", 6000);
        return;
      }
      docvault.toast("Deleted.", "success", 2500);
      load();
    });
  }

  load();
})();
