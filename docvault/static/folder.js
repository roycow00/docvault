// docvault — folder picker + batch ingest.
// Builds an interactive checkbox tree from POST /api/folder/scan.
// Streams batch results from POST /api/folder/ingest (NDJSON).
(() => {
  const params = new URLSearchParams(location.search);
  const root = params.get("root");

  const $ = id => document.getElementById(id);
  const elTree    = $("tree");
  const elBanner  = $("banner");
  const elRoot    = $("folder-root");
  const elSummary = $("folder-summary");
  const elIngest  = $("ingest");
  const elUseAi   = $("use-ai");
  const elResults = $("results");
  const elProgress = $("progress");
  const elResultsRows = $("results-rows");
  const elSelAll  = $("select-all");
  const elSelNone = $("select-none");
  const elExpAll  = $("expand-all");
  const elColAll  = $("collapse-all");

  if (!root) {
    setBanner("No ?root= folder provided.", "error");
    return;
  }
  elRoot.textContent = root;

  function setBanner(msg, kind = "info") {
    elBanner.className = `banner ${kind}`;
    elBanner.textContent = msg;
    elBanner.classList.remove("hidden");
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function fmtSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
    return (b / 1073741824).toFixed(1) + " GB";
  }

  // Build a nested tree from a flat list of {rel, abs, size, mime}.
  function buildTree(files) {
    const root = { name: "", type: "dir", children: new Map() };
    for (const f of files) {
      const parts = f.rel.split("/");
      let node = root;
      for (let i = 0; i < parts.length - 1; i++) {
        const name = parts[i];
        if (!node.children.has(name)) {
          node.children.set(name, { name, type: "dir", children: new Map() });
        }
        node = node.children.get(name);
      }
      const leaf = { name: parts[parts.length - 1], type: "file", file: f };
      node.children.set(parts[parts.length - 1], leaf);
    }
    return root;
  }

  function renderTree(root) {
    // Recursive DOM build. Each <li> carries its node ref via JS map for state ops.
    const list = document.createElement("ul");
    for (const child of [...root.children.values()].sort(sortDirsFirst)) {
      list.appendChild(renderNode(child));
    }
    elTree.innerHTML = "";
    elTree.appendChild(list);
  }

  function sortDirsFirst(a, b) {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  }

  function renderNode(node) {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "node";

    const toggle = document.createElement("span");
    toggle.className = "toggle";
    toggle.textContent = node.type === "dir" ? "▾" : "";
    if (node.type !== "dir") toggle.classList.add("empty");
    if (node.type === "dir") {
      toggle.addEventListener("click", () => {
        li.classList.toggle("collapsed");
        toggle.textContent = li.classList.contains("collapsed") ? "▸" : "▾";
      });
    }
    row.appendChild(toggle);

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb._node = node;
    cb.addEventListener("change", () => {
      // Cascade down
      li.querySelectorAll('input[type="checkbox"]').forEach(c => {
        c.checked = cb.checked;
        c.indeterminate = false;
      });
      // Cascade up
      updateAncestorState(li);
    });
    row.appendChild(cb);

    const name = document.createElement("span");
    name.className = "name " + (node.type === "dir" ? "dir" : "file");
    name.textContent = node.name + (node.type === "dir" ? "/" : "");
    row.appendChild(name);

    if (node.type === "file") {
      const size = document.createElement("span");
      size.className = "size";
      size.textContent = fmtSize(node.file.size);
      row.appendChild(size);
    }

    li.appendChild(row);
    li._cb = cb;

    if (node.type === "dir") {
      const sub = document.createElement("ul");
      for (const child of [...node.children.values()].sort(sortDirsFirst)) {
        sub.appendChild(renderNode(child));
      }
      li.appendChild(sub);
    }
    return li;
  }

  function updateAncestorState(li) {
    // Walk up from `li` updating each ancestor dir's checkbox to checked /
    // unchecked / indeterminate based on its descendants' state.
    let parentLi = li.parentElement && li.parentElement.closest("li");
    while (parentLi) {
      const cbs = parentLi.querySelectorAll(':scope > ul input[type="checkbox"]');
      let on = 0, off = 0;
      cbs.forEach(c => c.checked ? on++ : off++);
      const own = parentLi._cb;
      if (on === 0)        { own.checked = false; own.indeterminate = false; }
      else if (off === 0)  { own.checked = true;  own.indeterminate = false; }
      else                 { own.checked = false; own.indeterminate = true;  }
      parentLi = parentLi.parentElement && parentLi.parentElement.closest("li");
    }
  }

  function selectedFiles() {
    const out = [];
    elTree.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (cb.checked && cb._node && cb._node.type === "file") {
        out.push(cb._node.file.rel);
      }
    });
    return out;
  }

  async function load() {
    elTree.textContent = "scanning…";
    let scan;
    try {
      const r = await fetch("/api/folder/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root }),
      });
      if (!r.ok) {
        setBanner("scan failed: " + await r.text(), "error");
        elTree.textContent = "";
        return;
      }
      scan = await r.json();
    } catch (e) {
      setBanner("scan request failed: " + e.message, "error");
      elTree.textContent = "";
      return;
    }
    elRoot.textContent = scan.root;
    let summary = `${scan.files.length} file(s)`;
    if (scan.truncated) summary += " (scan capped — too many files; refine the folder)";
    if (scan.skipped.length) summary += `, ${scan.skipped.length} skipped`;
    elSummary.textContent = summary;
    if (scan.files.length === 0) {
      elTree.textContent = "(no ingestable files found in this folder)";
      elIngest.disabled = true;
      return;
    }
    const tree = buildTree(scan.files);
    renderTree(tree);
  }

  elSelAll.addEventListener("click",  () => elTree.querySelectorAll('input[type="checkbox"]').forEach(c => { c.checked = true;  c.indeterminate = false; }));
  elSelNone.addEventListener("click", () => elTree.querySelectorAll('input[type="checkbox"]').forEach(c => { c.checked = false; c.indeterminate = false; }));
  elExpAll.addEventListener("click",  () => elTree.querySelectorAll("li.collapsed").forEach(li => { li.classList.remove("collapsed"); const t = li.querySelector(":scope > .node > .toggle"); if (t && !t.classList.contains("empty")) t.textContent = "▾"; }));
  elColAll.addEventListener("click",  () => elTree.querySelectorAll("li").forEach(li => { if (li.querySelector(":scope > ul")) { li.classList.add("collapsed"); const t = li.querySelector(":scope > .node > .toggle"); if (t && !t.classList.contains("empty")) t.textContent = "▸"; } }));

  elIngest.addEventListener("click", async () => {
    const sel = selectedFiles();
    if (sel.length === 0) {
      setBanner("Nothing selected.", "error");
      return;
    }
    if (sel.length > 200 && !confirm(`About to ingest ${sel.length} files. Continue?`)) return;

    const mode = document.querySelector('input[name="mode"]:checked').value;
    const useAi = elUseAi.checked;

    elIngest.disabled = true;
    elBanner.classList.add("hidden");
    elResults.classList.remove("hidden");
    elResultsRows.innerHTML = "";
    elProgress.textContent = `0 / ${sel.length} processed…`;

    let processed = 0;
    let r;
    try {
      r = await fetch("/api/folder/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root, rel_paths: sel, mode, use_ai: useAi }),
      });
    } catch (e) {
      setBanner("ingest request failed: " + e.message, "error");
      elIngest.disabled = false;
      return;
    }
    if (!r.ok) {
      setBanner("ingest failed: " + await r.text(), "error");
      elIngest.disabled = false;
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
        if (evt.done) {
          elProgress.textContent =
            `Done — ${evt.ok} ingested, ${evt.duplicate} duplicate, ${evt.error} error (of ${evt.total}).`;
          elIngest.disabled = false;
          continue;
        }
        processed++;
        elProgress.textContent = `${processed} / ${sel.length} processed…`;
        const tr = document.createElement("tr");
        const detail = evt.error || (evt.title ? `title: ${evt.title}` : "") + (evt.ai_error ? ` (ai: ${evt.ai_error})` : "");
        tr.innerHTML = `
          <td>${esc(evt.rel)}</td>
          <td class="status-${esc(evt.status)}">${esc(evt.status)}</td>
          <td>${esc(detail)}</td>
        `;
        elResultsRows.appendChild(tr);
      }
    }
  });

  load();
})();
