// docvault — table view
(() => {
  const rows = document.getElementById("rows");
  const empty = document.getElementById("empty");
  const search = document.getElementById("search");
  const count = document.getElementById("count");
  const statusbar = document.getElementById("statusbar");
  const dlg = document.getElementById("delete-dialog");

  let docs = [];
  let cfg = null;
  let sortKey = "ingested";
  let sortDir = -1; // newest first by default
  let highlight = new URLSearchParams(location.search).get("highlight") || null;

  async function load() {
    try {
      const r = await fetch("/api/docs");
      docs = await r.json();
    } catch (e) {
      docs = [];
      setEmpty("Could not reach the docvault server. Is it still running?");
    }
    render();
  }

  async function loadConfig() {
    try {
      cfg = await (await fetch("/api/config")).json();
      statusbar.textContent = `docvault ${cfg.version} · vault: ${cfg.vault_root} · deleted files stay in trash for ${cfg.trash_retention_days} days`;
      const hint = document.getElementById("del-file-hint");
      if (hint) hint.textContent = `Move both to trash; recoverable for ${cfg.trash_retention_days} days.`;
    } catch (e) { /* cosmetic only */ }
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
    if (d.location.source === "onedrive_personal_vault") {
      out.push('<span class="badge lock" title="OneDrive Personal Vault — may require unlock">🔒</span>');
    }
    if (!d.accessible && d.location.source !== "onedrive_personal_vault") {
      out.push('<span class="badge missing" title="File missing or inaccessible">⚠️</span>');
    }
    return out.join("");
  }

  function locChip(d) {
    return d.location.type === "vault"
      ? '<span class="loc-chip vault" title="Managed copy inside the vault">vault</span>'
      : `<span class="loc-chip" title="Reference to an external file: ${esc(d.location.resolved)}">ref</span>`;
  }

  function rowHtml(d) {
    const tags = (d.tags || []).map(t => `<span class="tag" data-tag="${esc(t)}" title="Filter by tag">${esc(t)}</span>`).join(" ");
    const snippet = d.intro ? `<div class="intro-snippet" title="${esc(d.intro)}">${esc(d.intro)}</div>` : "";
    return `
      <tr data-sha="${d.sha256}">
        <td>
          <div class="title-cell">
            ${badges(d)}
            <a href="#" data-action="open" title="Open with default app — ${esc(d.original_filename)}">${esc(d.title || d.original_filename)}</a>
          </div>
          ${snippet}
        </td>
        <td>${tags}</td>
        <td>${locChip(d)}</td>
        <td class="date">${fmtDate(d.ingested)}</td>
        <td class="size">${fmtSize(d.size)}</td>
        <td class="actions">
          <a href="/static/edit.html?sha=${encodeURIComponent(d.sha256)}">edit</a>
          <button data-action="show" title="Reveal in Explorer">show</button>
          <button data-action="delete" class="danger">del</button>
        </td>
      </tr>
    `;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function setEmpty(text) {
    empty.textContent = text;
    empty.classList.remove("hidden");
  }

  function compare(a, b) {
    let va = a[sortKey], vb = b[sortKey];
    if (sortKey === "title") { va = (va || a.original_filename).toLowerCase(); vb = (vb || b.original_filename).toLowerCase(); }
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  }

  function applyFilter() {
    const q = search.value.trim().toLowerCase();
    const filtered = (!q ? [...docs] : docs.filter(d => {
      const blob = (
        d.title + " " + (d.intro || "") + " " +
        (d.tags || []).join(" ") + " " + (d.original_filename || "")
      ).toLowerCase();
      return blob.includes(q);
    })).sort(compare);

    rows.innerHTML = filtered.map(rowHtml).join("");
    if (filtered.length === 0) {
      if (docs.length === 0) {
        empty.innerHTML = 'No documents yet. Right-click a file in Windows Explorer and choose <b>Ingest into docvault</b>, or run <code>docvault ingest &lt;file&gt;</code>.';
        empty.classList.remove("hidden");
      } else {
        setEmpty(`No documents match “${search.value.trim()}”.`);
      }
    } else {
      empty.classList.add("hidden");
    }
    count.textContent = filtered.length === docs.length
      ? `${docs.length} document${docs.length === 1 ? "" : "s"}`
      : `${filtered.length} / ${docs.length}`;

    if (highlight) {
      const tr = rows.querySelector(`tr[data-sha="${CSS.escape(highlight)}"]`);
      if (tr) {
        tr.scrollIntoView({ block: "center" });
        tr.classList.add("flash");
      }
      highlight = null;
    }
  }

  function render() { applyFilter(); }

  search.addEventListener("input", applyFilter);
  search.addEventListener("keydown", ev => {
    if (ev.key === "Escape") { search.value = ""; applyFilter(); }
  });

  document.querySelectorAll("thead th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir = -sortDir;
      else { sortKey = key; sortDir = key === "title" ? 1 : -1; }
      applyFilter();
    });
  });

  rows.addEventListener("click", async ev => {
    const tagChip = ev.target.closest(".tag[data-tag]");
    if (tagChip) {
      search.value = tagChip.dataset.tag;
      applyFilter();
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
        alert("Could not open: " + txt + (doc.location.source === "onedrive_personal_vault"
          ? "\n\nIf the file is in OneDrive Personal Vault, unlock it first."
          : ""));
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
    document.getElementById("del-loc-type").textContent = doc.location.type === "vault" ? "managed copy in vault" : "external file (reference)";
    document.getElementById("del-path").textContent = doc.location.resolved;
    const hint = document.getElementById("del-file-hint");
    const days = cfg ? cfg.trash_retention_days : 90;
    hint.textContent = doc.location.type === "external"
      ? `Moves the EXTERNAL file into the vault trash too; recoverable for ${days} days.`
      : `Move both to trash; recoverable for ${days} days.`;
    dlg.returnValue = "";
    dlg.showModal();

    dlg.addEventListener("close", async function once() {
      dlg.removeEventListener("close", once);
      const action = dlg.returnValue;
      if (!action || action === "cancel") return;
      const r = await fetch(`/api/docs/${encodeURIComponent(doc.sha256)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!r.ok) {
        alert("Delete failed: " + await r.text());
        return;
      }
      load();
    });
  }

  loadConfig();
  load();
})();
