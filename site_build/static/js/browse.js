// Browse-table: filter input + click-to-sort column headers.
(function() {
  const input = document.getElementById("filter-input");
  const hideProposed = document.getElementById("hide-proposed");
  const table = document.querySelector(".browse-table tbody");
  if (!table) return;

  const rows = Array.from(table.querySelectorAll("tr"));
  const headers = document.querySelectorAll(".browse-table th.sortable");

  // Column index map. Mirrors the table's column order.
  const COL = {
    course: 0,
    term: 1,
    title: 2,
    sections: 3,
    cases: 4,
  };
  const NUMERIC = new Set(["sections", "cases"]);
  // For numeric columns, first-click goes descending; for string columns,
  // first-click goes ascending. This matches the user instinct: "show me
  // largest first" for counts, "alphabetical" for names.
  const FIRST_CLICK_DESC = new Set(["sections", "cases"]);

  // Term chrono ordering. Each year contributes a (year * 10 + season) key
  // where Spring=1 < Summer=2 < Fall=3 < Winter=4 (Winter unlikely; included
  // defensively). Allows numeric sort across terms.
  function termKey(t) {
    if (!t) return -Infinity;
    const m = t.match(/^(Spring|Summer|Fall|Winter)\s+(\d{4})$/i);
    if (!m) return -Infinity;
    const season = { spring: 1, summer: 2, fall: 3, winter: 4 }[m[1].toLowerCase()];
    return parseInt(m[2], 10) * 10 + season;
  }

  // Numeric extractor: parse the text content as int, or 0 if blank.
  function numKey(t) {
    const n = parseInt((t || "").trim(), 10);
    return Number.isFinite(n) ? n : 0;
  }

  function getKey(row, colName) {
    const idx = COL[colName];
    const cell = row.cells[idx];
    const text = (cell ? cell.textContent : "").trim();
    if (colName === "term") return termKey(text);
    if (NUMERIC.has(colName)) return numKey(text);
    return text.toLowerCase();
  }

  function compare(a, b) {
    if (a < b) return -1;
    if (a > b) return 1;
    return 0;
  }

  function sortBy(colName, descending) {
    rows.sort((a, b) => {
      const ka = getKey(a, colName);
      const kb = getKey(b, colName);
      // Push empty/sentinel values to the bottom regardless of direction.
      const aEmpty = ka === -Infinity || ka === "";
      const bEmpty = kb === -Infinity || kb === "";
      if (aEmpty && !bEmpty) return 1;
      if (bEmpty && !aEmpty) return -1;
      const cmp = compare(ka, kb);
      return descending ? -cmp : cmp;
    });
    rows.forEach(row => table.appendChild(row));
  }

  function updateFilter() {
    const q = (input ? input.value : "").toLowerCase().trim();
    const hide = hideProposed && hideProposed.checked;
    rows.forEach(row => {
      const text = row.textContent.toLowerCase();
      const matches = !q || text.includes(q);
      const proposed = row.classList.contains("proposed-row");
      const visible = matches && (!hide || !proposed);
      row.style.display = visible ? "" : "none";
    });
  }

  function setActiveHeader(colName, descending) {
    headers.forEach(h => {
      h.classList.remove("sort-asc", "sort-desc");
      if (h.dataset.sort === colName) {
        h.classList.add(descending ? "sort-desc" : "sort-asc");
      }
    });
  }

  if (input) input.addEventListener("input", updateFilter);
  if (hideProposed) hideProposed.addEventListener("change", updateFilter);

  headers.forEach(h => {
    h.addEventListener("click", () => {
      const colName = h.dataset.sort;
      const currentlyAsc = h.classList.contains("sort-asc");
      const currentlyDesc = h.classList.contains("sort-desc");
      let descending;
      if (currentlyAsc) descending = true;
      else if (currentlyDesc) descending = false;
      else descending = FIRST_CLICK_DESC.has(colName);
      sortBy(colName, descending);
      setActiveHeader(colName, descending);
    });
  });

  // Default sort: term ascending (chronological)
  sortBy("term", false);
  setActiveHeader("term", false);
})();
