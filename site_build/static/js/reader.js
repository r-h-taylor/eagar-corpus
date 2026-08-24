// Three-column lecture reader
(function() {
  const data = window.LECTURE_DATA;
  if (!data) return;

  const columns = document.querySelector(".columns");
  const buttons = document.querySelectorAll(".layer-toggle");
  const popup = document.getElementById("register-popup");
  const popupBody = popup ? popup.querySelector(".popup-body") : null;
  const popupClose = popup ? popup.querySelector(".popup-close") : null;

  // Build reverse maps for cross-layer lookup
  const l3ToAnchor = data.anchor_map || {};
  const l2ToL3 = {};  // l2_id -> [l3_id, ...]
  Object.entries(l3ToAnchor).forEach(([l3_id, a]) => {
    (a.l2_ids || []).forEach(l2 => {
      if (!l2ToL3[l2]) l2ToL3[l2] = [];
      l2ToL3[l2].push(l3_id);
    });
  });

  // Mark paragraphs that have register notes
  const hasNote = new Set(Object.keys(data.register || {}));
  document.querySelectorAll(".register-marker").forEach(el => {
    if (hasNote.has(el.dataset.l3Id)) {
      el.classList.add("has-note");
    } else {
      el.style.display = "none";
    }
  });

  // ---------------------------------------------------------------
  // Layer toggle
  // ---------------------------------------------------------------
  function updateLayers() {
    const active = [];
    ["l3", "l2"].forEach(layer => {
      const btn = document.querySelector(`.layer-toggle[data-layer="${layer}"]`);
      const col = document.querySelector(`.column[data-layer="${layer}"]`);
      if (!btn || !col) { console.warn("missing element for layer", layer, "btn:", btn, "col:", col); return; }
      if (btn.classList.contains("active")) {
        active.push(layer);
        col.classList.add("visible");
      } else {
        col.classList.remove("visible");
      }
    });
    if (active.length === 0) {
      // Don't allow zero layers; re-enable L3
      const l3btn = document.querySelector('.layer-toggle[data-layer="l3"]');
      l3btn.classList.add("active");
      document.querySelector('.column[data-layer="l3"]').classList.add("visible");
      active.push("l3");
    }
    columns.setAttribute("data-active-layers", active.join(","));
  }

  buttons.forEach(btn => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("active");
      updateLayers();
    });
  });

  // ---------------------------------------------------------------
  // Click-to-sync scrolling
  // ---------------------------------------------------------------
  function clearActive() {
    document.querySelectorAll(".paragraph.active").forEach(el => el.classList.remove("active"));
  }

  function scrollToInColumn(columnEl, targetEl) {
    if (!columnEl.classList.contains("visible") || !targetEl) return;
    const containerRect = columnEl.getBoundingClientRect();
    const targetRect = targetEl.getBoundingClientRect();
    const offset = targetRect.top - containerRect.top + columnEl.scrollTop - 100;
    columnEl.scrollTo({ top: offset, behavior: "smooth" });
  }

  function syncFromL3(l3_id) {
    clearActive();
    // Highlight L3
    const l3El = document.querySelector(`.l3-paragraph[data-l3-id="${l3_id}"]`);
    if (l3El) l3El.classList.add("active");
    // Find linked L2 paragraphs
    const anchor = l3ToAnchor[l3_id];
    if (!anchor) return;
    (anchor.l2_ids || []).forEach(l2_id => {
      const l2El = document.querySelector(`.l2-paragraph[data-l2-id="${l2_id}"]`);
      if (l2El) {
        l2El.classList.add("active");
        const l2col = document.querySelector('.column[data-layer="l2"]');
        scrollToInColumn(l2col, l2El);
      }
    });
    // Scroll Layer 1 to the line range
    if (anchor.timestamp_range && anchor.timestamp_range.length >= 1) {
    }
  }

  function syncFromL2(l2_id) {
    clearActive();
    const l2El = document.querySelector(`.l2-paragraph[data-l2-id="${l2_id}"]`);
    if (l2El) l2El.classList.add("active");
    const l3_ids = l2ToL3[l2_id] || [];
    l3_ids.forEach(l3_id => {
      const l3El = document.querySelector(`.l3-paragraph[data-l3-id="${l3_id}"]`);
      if (l3El) {
        l3El.classList.add("active");
        const l3col = document.querySelector('.column[data-layer="l3"]');
        scrollToInColumn(l3col, l3El);
      }
    });
  }

  document.querySelectorAll(".l3-paragraph").forEach(el => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".register-marker")) return;
      syncFromL3(el.dataset.l3Id);
    });
  });

  document.querySelectorAll(".l2-paragraph").forEach(el => {
    el.addEventListener("click", () => {
      syncFromL2(el.dataset.l2Id);
    });
  });

  // ---------------------------------------------------------------
  // Register popup
  // ---------------------------------------------------------------
  if (popup && popupBody && popupClose) {
    document.querySelectorAll(".register-marker.has-note").forEach(marker => {
      marker.addEventListener("click", (e) => {
        e.stopPropagation();
        const l3_id = marker.dataset.l3Id;
        const noteHtml = data.register[l3_id];
        if (!noteHtml) return;
        popupBody.innerHTML = noteHtml;
        popup.classList.remove("hidden");
      });
    });
    popupClose.addEventListener("click", () => popup.classList.add("hidden"));
    popup.addEventListener("click", (e) => {
      if (e.target === popup) popup.classList.add("hidden");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") popup.classList.add("hidden");
    });
  }

  // ---------------------------------------------------------------
  // Section nav highlighting on scroll
  // ---------------------------------------------------------------
  const navLinks = document.querySelectorAll(".section-nav a");
  const l3col = document.querySelector('.column[data-layer="l3"]');
  if (l3col && navLinks.length > 0) {
    l3col.addEventListener("scroll", () => {
      const sections = document.querySelectorAll(".l3-section");
      let active = null;
      sections.forEach(sec => {
        const rect = sec.getBoundingClientRect();
        if (rect.top < window.innerHeight / 3) active = sec;
      });
      navLinks.forEach(a => a.classList.remove("active"));
      if (active) {
        const id = active.id;
        const link = document.querySelector(`.section-nav a[href="#${id}"]`);
        if (link) link.classList.add("active");
      }
    });
  }

  // ---------------------------------------------------------------
  // Keyboard navigation: ← / → jump to prev/next lecture
  // ---------------------------------------------------------------
  document.addEventListener("keydown", (e) => {
    // Ignore when typing in an input/textarea or when modifiers held
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    if (e.key === "ArrowLeft") {
      const prev = document.querySelector(".lec-nav-prev:not(.lec-nav-disabled)");
      if (prev && prev.href) { e.preventDefault(); window.location.href = prev.href; }
    } else if (e.key === "ArrowRight") {
      const next = document.querySelector(".lec-nav-next:not(.lec-nav-disabled)");
      if (next && next.href) { e.preventDefault(); window.location.href = next.href; }
    }
  });
})();
