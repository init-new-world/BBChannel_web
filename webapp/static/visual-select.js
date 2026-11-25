import { t } from "./i18n.js";

let activePopoverClose = null;

export function closeActiveVisualSelect(options = {}) {
  if (typeof activePopoverClose === "function") {
    activePopoverClose(options);
  }
}

function isSelectDisabled(selectEl) {
  return Boolean(!selectEl || selectEl.disabled || selectEl.matches(":disabled"));
}

function createThumbElement(imageUrl, thumbKind = "avatar", isNone = false) {
  const box = document.createElement("span");
  box.className = `visual-thumb-box is-${thumbKind}${isNone ? " is-none" : ""}`;
  box.setAttribute("aria-hidden", "true");
  if (imageUrl) {
    const img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.src = imageUrl;
    img.addEventListener("error", () => {
      img.hidden = true;
      box.classList.add("is-fallback");
    });
    box.append(img);
  } else {
    box.classList.add("is-fallback");
  }
  return box;
}

export function createVisualSelect(selectEl, {
  kind = "avatar",
  showInlineThumb = false,
  minPopoverWidth = 320,
  maxRenderedItems = 160,
  getInlineThumb = null,
  getItems = () => [],
  getSearchPlaceholder = () => t("Search..."),
  getEmptyText = () => t("No matching options."),
  getFilters = null,
} = {}) {
  if (!selectEl) {
    return { sync() {}, close() {} };
  }

  const wrapper = document.createElement("span");
  wrapper.className = `visual-select-control visual-select-${kind}${showInlineThumb ? " has-inline-thumb" : ""}`;
  selectEl.parentNode?.insertBefore(wrapper, selectEl);

  let inlineThumbHost = null;
  let lastInlineThumbKey = null;
  if (showInlineThumb) {
    inlineThumbHost = document.createElement("span");
    inlineThumbHost.className = `visual-select-inline-thumb is-${kind}`;
    inlineThumbHost.setAttribute("aria-hidden", "true");
    wrapper.append(inlineThumbHost);
  }
  wrapper.append(selectEl);

  const listboxId = `visual-select-listbox-${Math.random().toString(36).slice(2, 9)}`;
  selectEl.setAttribute("aria-expanded", "false");

  let popover = null;
  let searchInput = null;
  let countBadge = null;
  let filterHost = null;
  let listHost = null;
  let filterValues = {};
  let highlightedIndex = 0;
  let visibleOptionButtons = [];
  let cleanupListeners = null;
  let lastSyncFingerprint = "";

  function isCurrentOptionDisabled() {
    return Boolean(selectEl.selectedOptions?.[0]?.disabled);
  }

  function computeSyncFingerprint(items, definitions) {
    const filterKey = Array.isArray(definitions)
      ? definitions.map((g) => `${g.key}:${g.label || ""}:${(g.options || []).map((o) => `${o.value}=${o.label}`).join(",")}`).join("|")
      : "";
    const itemKey = items
      .map((it) => `${it.value}\x1f${it.label}\x1f${it.disabled ? 1 : 0}\x1f${it.imageUrl || ""}\x1f${it.subtitle || ""}`)
      .join("\x1e");
    return `${selectEl.value}|${isCurrentOptionDisabled() ? 1 : 0}|${getSearchPlaceholder()}|${filterKey}|${itemKey}`;
  }

  function renderInlineThumb() {
    if (!inlineThumbHost || typeof getInlineThumb !== "function") return;
    const info = getInlineThumb();
    const url = info?.url || "";
    const isNone = Boolean(info?.isNone);
    const key = `${url}|${isNone ? "1" : "0"}`;
    if (key === lastInlineThumbKey) return;
    lastInlineThumbKey = key;
    inlineThumbHost.replaceChildren(createThumbElement(url, kind, isNone));
  }

  function positionPopover() {
    if (!popover) return;
    if (!selectEl.isConnected || selectEl.offsetParent === null || isSelectDisabled(selectEl)) {
      close({ restoreFocus: false });
      return;
    }
    const anchor = wrapper.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const scrollHost = wrapper.closest(".preset-form");
    if (scrollHost) {
      const hostRect = scrollHost.getBoundingClientRect();
      if (anchor.bottom < hostRect.top + 4 || anchor.top > hostRect.bottom - 4) {
        close({ restoreFocus: false });
        return;
      }
    } else if (anchor.bottom < 0 || anchor.top > viewportH) {
      close({ restoreFocus: false });
      return;
    }
    const margin = 8;
    const desiredWidth = Math.min(
      Math.max(anchor.width, minPopoverWidth),
      Math.max(220, viewportW - margin * 2),
    );
    const left = Math.max(margin, Math.min(anchor.left, viewportW - desiredWidth - margin));

    const clampedAnchorTop = Math.max(margin, Math.min(viewportH - margin, anchor.top));
    const clampedAnchorBottom = Math.max(margin, Math.min(viewportH - margin, anchor.bottom));
    const spaceBelow = viewportH - clampedAnchorBottom - margin - 4;
    const spaceAbove = clampedAnchorTop - margin - 4;
    const placeAbove = spaceBelow < 230 && spaceAbove > spaceBelow;
    const availableHeight = Math.max(160, Math.min(400, placeAbove ? spaceAbove : spaceBelow));

    popover.style.width = `${Math.round(desiredWidth)}px`;
    popover.style.left = `${Math.round(left)}px`;
    popover.style.maxHeight = `${Math.round(availableHeight)}px`;
    if (placeAbove) {
      popover.style.top = "auto";
      popover.style.bottom = `${Math.round(Math.max(margin, viewportH - clampedAnchorTop + 4))}px`;
    } else {
      popover.style.bottom = "auto";
      popover.style.top = `${Math.round(Math.max(margin, clampedAnchorBottom + 4))}px`;
    }
  }

  function selectValue(value) {
    close({ restoreFocus: true });
    if (isSelectDisabled(selectEl)) return;
    const wasDisabled = isCurrentOptionDisabled();
    if (selectEl.value !== value || wasDisabled) {
      const matchingIndex = [...selectEl.options].findIndex(
        (opt) => !opt.disabled && opt.value === value,
      );
      if (matchingIndex >= 0) {
        selectEl.selectedIndex = matchingIndex;
      } else {
        selectEl.value = value;
      }
      selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    }
    renderInlineThumb();
  }

  function syncHighlight(scrollIntoView = false) {
    visibleOptionButtons.forEach((btn, idx) => {
      const active = idx === highlightedIndex;
      btn.classList.toggle("is-highlighted", active);
      if (active && scrollIntoView) {
        btn.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function renderFilterControls() {
    if (!filterHost) return;
    const definitions = typeof getFilters === "function" ? getFilters() : [];
    if (!Array.isArray(definitions) || !definitions.length) {
      filterHost.hidden = true;
      filterHost.replaceChildren();
      return;
    }
    filterHost.hidden = false;
    const frag = document.createDocumentFragment();
    for (const group of definitions) {
      if (!(group.key in filterValues)) {
        filterValues[group.key] = group.defaultValue ?? "all";
      }
      const row = document.createElement("div");
      row.className = "visual-select-filter-row";
      if (group.label) {
        const lbl = document.createElement("span");
        lbl.className = "visual-select-filter-label";
        lbl.textContent = group.label;
        row.append(lbl);
      }
      for (const opt of group.options || []) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `chip-button${filterValues[group.key] === opt.value ? " active" : ""}`;
        chip.textContent = opt.label;
        chip.addEventListener("click", () => {
          filterValues[group.key] = opt.value;
          renderFilterControls();
          renderOptions({ scrollSelected: false });
          searchInput?.focus({ preventScroll: true });
        });
        row.append(chip);
      }
      frag.append(row);
    }
    filterHost.replaceChildren(frag);
  }

  function itemMatches(item, query, definitions) {
    if (Array.isArray(definitions)) {
      for (const group of definitions) {
        const activeVal = filterValues[group.key] ?? group.defaultValue ?? "all";
        if (activeVal !== "all" && typeof group.predicate === "function") {
          if (!group.predicate(item, activeVal)) return false;
        }
      }
    }
    if (!query) return true;
    const haystack = `${item.label || ""} ${item.subtitle || ""} ${item.searchText || ""}`.toLowerCase();
    return haystack.includes(query);
  }

  function buildOptionRow(item, currentVal, currentDisabled) {
    const btn = document.createElement("button");
    btn.type = "button";
    const isSelected = !currentDisabled && item.value === currentVal && !item.disabled;
    btn.className = `visual-select-option is-${kind}${isSelected ? " is-selected" : ""}`;
    btn.dataset.visualOptionValue = item.value;
    btn.disabled = Boolean(item.disabled);
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", String(isSelected));

    btn.append(createThumbElement(item.imageUrl || "", item.thumbKind || kind, Boolean(item.isNone)));

    const main = document.createElement("span");
    main.className = "visual-option-main";

    const top = document.createElement("span");
    top.className = "visual-option-top";

    const title = document.createElement("span");
    title.className = "visual-option-label";
    title.textContent = item.label;
    title.title = item.label;
    top.append(title);

    if (Array.isArray(item.badges) && item.badges.length) {
      const badges = document.createElement("span");
      badges.className = "visual-option-badges";
      for (const b of item.badges) {
        if (!b || !b.text) continue;
        const pill = document.createElement("span");
        pill.className = `visual-option-badge ${b.className || ""}`.trim();
        pill.textContent = b.text;
        badges.append(pill);
      }
      top.append(badges);
    }
    main.append(top);

    if (Array.isArray(item.skillIcons) && item.skillIcons.length) {
      const skillsRow = document.createElement("span");
      skillsRow.className = "visual-option-skills";
      for (const sk of item.skillIcons) {
        const chip = document.createElement("span");
        chip.className = "visual-option-skill-chip";
        if (sk.tooltip) chip.title = sk.tooltip;
        if (sk.url) {
          const icon = document.createElement("img");
          icon.src = sk.url;
          icon.alt = "";
          icon.loading = "lazy";
          icon.className = "visual-option-skill-icon";
          icon.addEventListener("error", () => { icon.hidden = true; });
          chip.append(icon);
        }
        if (sk.label) {
          const txt = document.createElement("span");
          txt.textContent = sk.label;
          chip.append(txt);
        }
        skillsRow.append(chip);
      }
      main.append(skillsRow);
    } else if (item.subtitle) {
      const sub = document.createElement("span");
      sub.className = "visual-option-sub";
      sub.textContent = item.subtitle;
      sub.title = item.subtitle;
      main.append(sub);
    }

    btn.append(main);

    if (isSelected) {
      const check = document.createElement("span");
      check.className = "visual-option-check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";
      btn.append(check);
    }

    btn.addEventListener("click", () => {
      if (!btn.disabled) selectValue(item.value);
    });
    return btn;
  }

  function renderOptions({ scrollSelected = false } = {}) {
    if (!listHost) return;
    const allItems = getItems();
    const definitions = typeof getFilters === "function" ? getFilters() : [];
    const query = (searchInput?.value || "").trim().toLowerCase();
    const matched = allItems.filter((item) => itemMatches(item, query, definitions));
    const currentVal = selectEl.value;
    const currentDisabled = isCurrentOptionDisabled();

    if (countBadge) {
      const selectableCount = matched.filter((item) => !item.isNone && !item.disabled).length;
      countBadge.textContent = String(selectableCount);
    }

    const shown = matched.slice(0, maxRenderedItems);
    if (!currentDisabled) {
      const selectedMatchIdx = matched.findIndex((item) => !item.disabled && item.value === currentVal);
      if (selectedMatchIdx >= maxRenderedItems) {
        const selectedItem = matched[selectedMatchIdx];
        const insertAt = shown[0]?.isNone ? 1 : 0;
        shown.splice(insertAt, 0, selectedItem);
        if (shown.length > maxRenderedItems) shown.pop();
      }
    }
    const frag = document.createDocumentFragment();
    visibleOptionButtons = [];

    for (const item of shown) {
      const btn = buildOptionRow(item, currentVal, currentDisabled);
      if (!btn.disabled) {
        const btnIndex = visibleOptionButtons.length;
        btn.addEventListener("pointerenter", () => {
          highlightedIndex = btnIndex;
          syncHighlight(false);
        });
        visibleOptionButtons.push(btn);
      }
      frag.append(btn);
    }

    if (matched.length > shown.length) {
      const more = document.createElement("div");
      more.className = "visual-select-hint";
      more.textContent = t("Showing first {shown} of {total} items — narrow with filters or search.", {
        shown: shown.length,
        total: matched.length,
      });
      frag.append(more);
    } else if (!shown.length) {
      const empty = document.createElement("div");
      empty.className = "visual-select-hint";
      empty.textContent = getEmptyText();
      frag.append(empty);
    }

    listHost.replaceChildren(frag);

    const selectedIdx = currentDisabled
      ? -1
      : visibleOptionButtons.findIndex((btn) => btn.dataset.visualOptionValue === currentVal);
    highlightedIndex = selectedIdx >= 0 ? selectedIdx : 0;
    syncHighlight(scrollSelected);
    positionPopover();
  }

  function close({ restoreFocus = false } = {}) {
    if (!popover) return;
    const node = popover;
    popover = null;
    searchInput = null;
    countBadge = null;
    filterHost = null;
    listHost = null;
    visibleOptionButtons = [];
    lastSyncFingerprint = "";
    wrapper.classList.remove("is-open");
    selectEl.setAttribute("aria-expanded", "false");
    selectEl.removeAttribute("aria-controls");
    if (cleanupListeners) {
      cleanupListeners();
      cleanupListeners = null;
    }
    if (activePopoverClose === close) {
      activePopoverClose = null;
    }
    node.remove();
    if (restoreFocus && selectEl.isConnected && !isSelectDisabled(selectEl)) {
      selectEl.focus({ preventScroll: true });
    }
  }

  function open() {
    if (isSelectDisabled(selectEl)) return;
    if (popover) {
      close({ restoreFocus: true });
      return;
    }
    closeActiveVisualSelect({ restoreFocus: false });
    activePopoverClose = close;
    filterValues = {};

    const hostRoot = selectEl.closest("dialog") || document.body;
    popover = document.createElement("div");
    popover.className = `visual-select-popover visual-popover-${kind}`;
    popover.dataset.visualSelectFor = selectEl.id || selectEl.dataset.teamSlot || kind;

    const header = document.createElement("div");
    header.className = "visual-select-header";
    searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "field visual-select-search";
    searchInput.placeholder = getSearchPlaceholder();
    searchInput.setAttribute("role", "combobox");
    searchInput.setAttribute("aria-autocomplete", "list");
    searchInput.setAttribute("aria-controls", listboxId);
    searchInput.setAttribute("aria-label", getSearchPlaceholder());
    searchInput.autocomplete = "off";
    searchInput.spellcheck = false;
    searchInput.addEventListener("input", () => renderOptions({ scrollSelected: false }));

    countBadge = document.createElement("span");
    countBadge.className = "visual-select-count";
    header.append(searchInput, countBadge);

    filterHost = document.createElement("div");
    filterHost.className = "visual-select-filters";
    filterHost.hidden = true;

    listHost = document.createElement("div");
    listHost.id = listboxId;
    listHost.className = "visual-select-list";
    listHost.setAttribute("role", "listbox");

    popover.append(header, filterHost, listHost);
    hostRoot.append(popover);
    wrapper.classList.add("is-open");
    selectEl.setAttribute("aria-expanded", "true");
    selectEl.setAttribute("aria-controls", listboxId);

    renderFilterControls();
    renderOptions({ scrollSelected: true });
    lastSyncFingerprint = computeSyncFingerprint(
      getItems(),
      typeof getFilters === "function" ? getFilters() : [],
    );

    const onPointerDown = (event) => {
      if (!popover) return;
      if (popover.contains(event.target) || wrapper.contains(event.target)) return;
      close({ restoreFocus: false });
    };

    const onKeyDown = (event) => {
      if (!popover) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close({ restoreFocus: true });
        return;
      }
      if (!popover.contains(document.activeElement) && document.activeElement !== selectEl) return;
      if (event.key === "ArrowDown") {
        if (visibleOptionButtons.length) {
          event.preventDefault();
          highlightedIndex = (highlightedIndex + 1) % visibleOptionButtons.length;
          syncHighlight(true);
        }
      } else if (event.key === "ArrowUp") {
        if (visibleOptionButtons.length) {
          event.preventDefault();
          highlightedIndex = (highlightedIndex - 1 + visibleOptionButtons.length) % visibleOptionButtons.length;
          syncHighlight(true);
        }
      } else if (event.key === "Enter") {
        // Only confirm the highlighted option when focus is on searchInput or selectEl;
        // let focused filter chips and Tab-focused option buttons handle Enter natively.
        if (document.activeElement !== searchInput && document.activeElement !== selectEl) {
          return;
        }
        const targetBtn = visibleOptionButtons[highlightedIndex];
        if (targetBtn && !targetBtn.disabled) {
          event.preventDefault();
          event.stopPropagation();
          selectValue(targetBtn.dataset.visualOptionValue);
        }
      }
    };

    const onScroll = (event) => {
      if (!popover) return;
      if (popover.contains(event.target)) return;
      positionPopover();
    };

    const onResize = () => positionPopover();
    const dialog = selectEl.closest("dialog");
    const onDialogClose = () => close({ restoreFocus: false });

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    dialog?.addEventListener("close", onDialogClose);

    cleanupListeners = () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
      dialog?.removeEventListener("close", onDialogClose);
    };

    requestAnimationFrame(() => {
      if (searchInput && popover) {
        searchInput.focus({ preventScroll: true });
        positionPopover();
      }
    });
  }

  let handledByPointer = false;
  wrapper.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || isSelectDisabled(selectEl)) return;
    event.preventDefault();
    handledByPointer = true;
    open();
  });
  wrapper.addEventListener("touchstart", (event) => {
    if (isSelectDisabled(selectEl)) return;
    event.preventDefault();
    handledByPointer = true;
    open();
  }, { passive: false });
  wrapper.addEventListener("click", (event) => {
    if (handledByPointer) {
      handledByPointer = false;
      event.preventDefault();
      return;
    }
    // Handles clicks on an enclosing <label> that synthesize click on selectEl.
    if (event.detail > 0 && !isSelectDisabled(selectEl)) {
      event.preventDefault();
      open();
    }
  });

  selectEl.addEventListener("change", renderInlineThumb);

  selectEl.addEventListener("keydown", (event) => {
    if (isSelectDisabled(selectEl)) return;
    if (event.altKey && event.key === "ArrowDown") {
      event.preventDefault();
      open();
    }
  });

  function sync() {
    renderInlineThumb();
    if (popover) {
      if (isSelectDisabled(selectEl)) {
        close({ restoreFocus: false });
        return;
      }
      const items = getItems();
      const definitions = typeof getFilters === "function" ? getFilters() : [];
      const fingerprint = computeSyncFingerprint(items, definitions);
      if (fingerprint === lastSyncFingerprint) {
        return;
      }
      lastSyncFingerprint = fingerprint;
      if (searchInput) {
        const placeholder = getSearchPlaceholder();
        searchInput.placeholder = placeholder;
        searchInput.setAttribute("aria-label", placeholder);
      }
      renderFilterControls();
      renderOptions({ scrollSelected: false });
    }
  }

  renderInlineThumb();

  return { sync, close, open };
}
