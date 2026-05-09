// docvault — table view
(() => {
  const rows = document.getElementById("rows");
  const empty = document.getElementById("empty");
  const search = document.getElementById("search");
  const count = document.getElementById("count");
  const dlg = document.getElementById("delete-dialog");

  let docs = [];
  let highlight = new URLSearchParams(location.search).get("highlight") || null;

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
    return `
      <tr data-sha="${d.sha256}">
        <td>
          <div class="title-cell">
            ${badges(d)}
            <a href="#" data-action="open" title="Open with default app">${esc(d.title || d.original_filename)}</a>
          </div>
        </td>
        <td>${tags}</td>
        <td>${fmtDate(d.ingested)}</td>
        <td>${fmtSize(d.size)}</td>
        <td class="actions">
          <a href="/static/edit.html?sha=${encodeURIComponent(d.sha256)}">edit</a>
          <button data-action="show">show</button>
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

  function applyFilter() {
    const q = search.value.trim().toLowerCase();
    const filtered = !q ? docs : docs.filter(d => {
      const blob = (d.title + " " + (d.intro || "") + " " + (d.tags || []).join(" ")).toLowerCase();
      return blob.includes(q);
    });
    rows.innerHTML = filtered.map(rowHtml).join("");
    empty.classList.toggle("hidden", filtered.length > 0);
    count.textContent = filtered.length === docs.length ? `${docs.length}` : `${filtered.length} / ${docs.length}`;

    if (highlight) {
      const tr = rows.querySelector(`tr[data-sha="${CSS.escape(highlight)}"]`);
      if (tr) {
        tr.scrollIntoView({ block: "center" });
        tr.classList.add("just-saved");
      }
      highlight = null;
    }
  }

  function render() { applyFilter(); }

  search.addEventListener("input", applyFilter);

  rows.addEventListener("click", async ev => {
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
    document.getElementById("del-loc-type").textContent = doc.location.type === "vault" ? "in vault" : "external file";
    document.getElementById("del-path").textContent = doc.location.resolved;
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
        alert("Delete failed: " + await r.text());
        return;
      }
      load();
    });
  }

  load();
})();
