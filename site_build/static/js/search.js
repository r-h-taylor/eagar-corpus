// Full-text search using lunr.js
(function() {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const status = document.getElementById("search-status");
  const scopes = document.querySelectorAll('input[name="scope"]');
  if (!input || !results) return;

  let docs = null;
  let index = null;

  async function load() {
    try {
      const resp = await fetch("data/search_docs.json");
      docs = await resp.json();
      index = lunr(function() {
        this.ref("id");
        this.field("content", { boost: 2 });
        this.field("lecture_title");
        this.field("course");
        this.field("cluster_id", { boost: 3 });
        docs.forEach(d => this.add(d));
      });
      status.textContent = `Ready. ${docs.length} documents indexed.`;
    } catch (e) {
      status.textContent = `Error loading index: ${e.message}`;
    }
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function highlight(text, query) {
    if (!query) return escape(text);
    const terms = query.split(/\s+/).filter(t => t.length > 1);
    let out = escape(text);
    terms.forEach(t => {
      const re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }

  function snippet(text, query) {
    if (!text) return "";
    if (!query) return escape(text.slice(0, 200));
    const terms = query.split(/\s+/).filter(t => t.length > 1);
    if (terms.length === 0) return escape(text.slice(0, 200));
    const lower = text.toLowerCase();
    let idx = -1;
    for (const t of terms) {
      idx = lower.indexOf(t.toLowerCase());
      if (idx >= 0) break;
    }
    if (idx < 0) return escape(text.slice(0, 200));
    const start = Math.max(0, idx - 60);
    const end = Math.min(text.length, idx + 200);
    let s = text.slice(start, end);
    if (start > 0) s = "…" + s;
    if (end < text.length) s = s + "…";
    return highlight(s, query);
  }

  function render(query) {
    if (!index || !query.trim()) {
      results.innerHTML = "";
      return;
    }
    let hits = [];
    try {
      hits = index.search(query);
    } catch (e) {
      // lunr.js raises on bad queries; try a relaxed version
      try {
        hits = index.search(query.split(/\s+/).map(t => t + "*").join(" "));
      } catch (e2) {
        results.innerHTML = `<p>Query error: ${escape(e2.message)}</p>`;
        return;
      }
    }
    const activeScopes = new Set(Array.from(scopes).filter(s => s.checked).map(s => s.value));
    const filtered = hits
      .map(h => ({ hit: h, doc: docs.find(d => d.id === h.ref) }))
      .filter(({ doc }) => doc && activeScopes.has(doc.type))
      .slice(0, 50);

    if (filtered.length === 0) {
      results.innerHTML = "<p>No results.</p>";
      return;
    }

    results.innerHTML = filtered.map(({ doc }) => {
      let url = "#", title = "", typeLabel = "";
      if (doc.type === "paragraph") {
        const anchorFrag = `l3-${(doc.l2_id || "").replace("§","s").replace(".","-")}`;
        // Look up the L3 anchor — we don't have it in the search doc, so link to lecture
        url = `lectures/${doc.video_id}.html`;
        title = `${doc.lecture_title} — ${doc.l2_id} [${doc.timestamp}]`;
        typeLabel = "Paragraph";
      } else if (doc.type === "case") {
        const safe = doc.cluster_id.replace(/[^a-zA-Z0-9_.-]/g, "_").slice(0, 120);
        url = `cases/${safe}.html`;
        title = `${doc.cluster_id} (${doc.appearance_count} appearances)`;
        typeLabel = "Case";
      } else if (doc.type === "lecture") {
        url = `lectures/${doc.video_id}.html`;
        title = `${doc.lecture_title} — ${doc.course}, ${doc.term}`;
        typeLabel = "Lecture";
      }
      return `
        <div class="search-result">
          <div class="result-type">${typeLabel}</div>
          <div class="result-title"><a href="${url}">${escape(title)}</a></div>
          <p class="result-snippet">${snippet(doc.content || "", query)}</p>
        </div>
      `;
    }).join("");
  }

  let debounce = null;
  input.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => render(input.value), 200);
  });
  scopes.forEach(s => s.addEventListener("change", () => render(input.value)));

  load();
})();
