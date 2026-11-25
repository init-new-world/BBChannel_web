import { t } from "./i18n.js";
import { editAssistEquipSource, inspectAssistEquipGrandSlots, inspectAssistEquipSource } from "./assist-equips-source.js";
import { createVisualSelect } from "./visual-select.js";

export function createPresetEquipEditor({ getEditor, source, request, onChange, onError }) {
  const section = document.querySelector("#preset-assist-equips");
  const controls = document.querySelector("#preset-assist-equip-controls");
  const list = document.querySelector("#preset-assist-equip-list");
  const picker = document.querySelector("#preset-assist-equip-source");
  const add = document.querySelector("#add-assist-equip");
  const clear = document.querySelector("#clear-assist-equips");
  const refresh = document.querySelector("#refresh-assist-equips");
  const status = document.querySelector("#preset-assist-equip-status");
  let usesEquip = false;
  let galleryQuery = "";

  const galleryBlock = document.createElement("div");
  galleryBlock.className = "preset-equip-gallery-block";
  galleryBlock.hidden = true;

  const galleryHeader = document.createElement("div");
  galleryHeader.className = "preset-equip-gallery-head";
  const galleryTitle = document.createElement("span");
  galleryTitle.className = "preset-equip-gallery-title";
  const gallerySearch = document.createElement("input");
  gallerySearch.type = "search";
  gallerySearch.className = "field preset-equip-gallery-search";
  gallerySearch.autocomplete = "off";
  gallerySearch.spellcheck = false;
  galleryHeader.append(galleryTitle, gallerySearch);

  const galleryGrid = document.createElement("div");
  galleryGrid.className = "preset-equip-gallery-grid";
  galleryBlock.append(galleryHeader, galleryGrid);
  list.insertAdjacentElement("afterend", galleryBlock);

  function equipImageUrl(name) {
    return `/api/equip-templates/${encodeURIComponent(name)}/image?location=active`;
  }

  const visualPicker = createVisualSelect(picker, {
    kind: "ce",
    showInlineThumb: true,
    minPopoverWidth: 340,
    getSearchPlaceholder: () => t("Filter CEs..."),
    getEmptyText: () => t("No CE templates matched."),
    getInlineThumb: () => {
      const val = picker.value;
      if (!val) return { url: "", isNone: true };
      return { url: equipImageUrl(val), isNone: false };
    },
    getItems: () => [...picker.options]
      .filter((opt) => opt.value)
      .map((opt) => ({
        value: opt.value,
        label: opt.textContent || opt.value,
        disabled: opt.disabled,
        imageUrl: equipImageUrl(opt.value),
        thumbKind: "ce",
      })),
  });

  async function loadCatalog(editor, catalog) {
    try {
      const payload = await request("/api/equip-templates");
      if (!Array.isArray(payload.templates) || payload.templates.some((item) => !item || typeof item.name !== "string")) {
        throw new Error(t("Invalid CE catalog."));
      }
      catalog.names = [...new Set(payload.templates.filter((item) => item.location === "active" && item.name).map((item) => item.name))];
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || t("CE catalog unavailable.");
    }
    if (getEditor() === editor && editor.equipCatalog === catalog) {
      const restoreFocus = catalog.restoreRefreshFocus && document.activeElement === document.body;
      render();
      if (restoreFocus && !controls.disabled && !refresh.disabled) refresh.focus();
    }
  }

  const GRAND_SLOT_BADGE_KEYS = {
    normal: "Normal CE",
    kizuna: "Bond CE",
    houshuu: "Reward CE",
  };

  function equipRow(name, available, slots = null) {
    const row = document.createElement("div");
    row.className = "preset-equip-row";
    row.dataset.assistEquipName = name;
    const thumbnail = document.createElement("div");
    thumbnail.className = "preset-equip-thumbnail";
    const caption = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = name;
    const note = document.createElement("small");
    note.textContent = available === false ? t("Unavailable") : "";
    note.hidden = available !== false;
    caption.append(label);
    if (Array.isArray(slots) && slots.length) {
      const badges = document.createElement("span");
      badges.className = "preset-equip-slot-badges";
      for (const slotKey of slots) {
        const badge = document.createElement("span");
        badge.className = "preset-equip-slot-badge";
        badge.textContent = t(GRAND_SLOT_BADGE_KEYS[slotKey] || slotKey);
        badges.append(badge);
      }
      caption.append(badges);
    }
    caption.append(note);
    if (available) {
      const image = document.createElement("img");
      image.alt = "";
      image.width = 88;
      image.height = 26;
      image.src = equipImageUrl(name);
      image.addEventListener("error", () => {
        image.hidden = true;
        note.hidden = false;
        note.textContent = t("Preview unavailable");
      });
      thumbnail.append(image);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button";
    button.title = t("Remove CE");
    button.setAttribute("aria-label", t("Remove CE"));
    const icon = document.createElement("img");
    icon.src = "/icons/trash-2.svg";
    icon.alt = "";
    icon.width = 16;
    icon.height = 16;
    button.append(icon);
    button.addEventListener("click", () => change("remove", name));
    row.append(thumbnail, caption, button);
    return row;
  }

  function renderGallery(available, selectedNames, locked) {
    galleryTitle.textContent = t("Click CE card to toggle");
    gallerySearch.placeholder = t("Filter CEs...");
    if (!available.length) {
      galleryBlock.hidden = true;
      galleryGrid.replaceChildren();
      return;
    }
    galleryBlock.hidden = false;
    gallerySearch.disabled = locked;
    const q = galleryQuery.trim().toLowerCase();
    const filtered = q
      ? available.filter((item) => item.toLowerCase().includes(q))
      : available;

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "preset-equip-gallery-empty";
      empty.textContent = t("No CE templates matched.");
      galleryGrid.replaceChildren(empty);
      return;
    }

    const frag = document.createDocumentFragment();
    for (const name of filtered) {
      const isSelected = selectedNames.includes(name);
      const card = document.createElement("button");
      card.type = "button";
      card.className = `preset-equip-gallery-card${isSelected ? " active" : ""}`;
      card.dataset.equipGalleryItem = name;
      card.disabled = locked;
      card.setAttribute("aria-pressed", String(isSelected));
      card.title = name;

      const thumbWrap = document.createElement("span");
      thumbWrap.className = "preset-equip-gallery-thumb";
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      img.src = equipImageUrl(name);
      img.addEventListener("error", () => {
        img.hidden = true;
        thumbWrap.classList.add("is-fallback");
      });
      thumbWrap.append(img);

      const text = document.createElement("span");
      text.className = "preset-equip-gallery-label";
      text.textContent = name;

      card.append(thumbWrap, text);
      if (isSelected) {
        const mark = document.createElement("span");
        mark.className = "preset-equip-gallery-check";
        mark.setAttribute("aria-hidden", "true");
        mark.textContent = "✓";
        card.append(mark);
      }
      card.addEventListener("click", () => {
        change(isSelected ? "remove" : "add", name);
      });
      frag.append(card);
    }
    galleryGrid.replaceChildren(frag);
  }

  gallerySearch.addEventListener("input", () => {
    galleryQuery = gallerySearch.value;
    const editor = getEditor();
    if (editor?.kind !== "settings") return;
    let selectedNames = [];
    let hasError = false;
    try {
      const info = inspectAssistEquipSource(source.value);
      selectedNames = info.names || [];
      hasError = Boolean(info.error);
    } catch {
      hasError = true;
    }
    renderGallery(
      editor.equipCatalog?.names || [],
      selectedNames,
      hasError || controls.disabled || editor.equipCatalog?.state !== "ready",
    );
  });

  function render(enabled = usesEquip) {
    usesEquip = Boolean(enabled);
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || !usesEquip || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") {
      visualPicker.close();
      return;
    }
    if (!editor.equipsInitialized) {
      section.open = false;
      galleryQuery = "";
      gallerySearch.value = "";
      editor.equipsInitialized = true;
    }
    let info;
    try {
      info = inspectAssistEquipSource(source.value);
    } catch (error) {
      controls.disabled = true;
      list.replaceChildren();
      galleryBlock.hidden = true;
      galleryGrid.replaceChildren();
      status.textContent = t(error.message);
      visualPicker.sync();
      return;
    }
    let catalog = editor.equipCatalog;
    if (!catalog) {
      catalog = { state: "loading", restoreRefreshFocus: document.activeElement === refresh };
      editor.equipCatalog = catalog;
      void loadCatalog(editor, catalog);
    }
    const names = info.names || [];
    const error = info.error ? t(info.error) : "";
    const focused = document.activeElement;
    const focusedRow = focused?.closest("[data-assist-equip-name]");
    const focusedGallery = focused?.closest("[data-equip-gallery-item]");
    const focusedGalleryName = focusedGallery?.dataset.equipGalleryItem || "";
    const focusedIndex = [...list.children].indexOf(focusedRow);
    const available = catalog.names || [];
    const slotsByName = inspectAssistEquipGrandSlots(source.value);
    list.replaceChildren(
      ...names.map((name) => equipRow(
        name,
        catalog.state === "ready" ? available.includes(name) : null,
        slotsByName ? slotsByName[name] : null,
      )),
    );
    const choices = available.filter((name) => !names.includes(name));
    const selected = picker.value;
    picker.replaceChildren(...(choices.length ? choices : [""]).map((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name || t("No unused active CEs");
      return option;
    }));
    if (choices.includes(selected)) picker.value = selected;
    picker.title = picker.selectedOptions[0]?.textContent || "";
    picker.disabled = Boolean(error) || catalog.state !== "ready" || !choices.length;
    add.disabled = picker.disabled;
    clear.disabled = !info.canClear;
    refresh.disabled = catalog.state === "loading";

    if (catalog.state === "ready") {
      renderGallery(available, names, Boolean(error) || controls.disabled);
    } else {
      galleryBlock.hidden = true;
      galleryGrid.replaceChildren();
    }
    visualPicker.sync();

    status.textContent = error || (!usesEquip ? t("Inactive for this recognition mode.")
      : catalog.state === "loading" ? t("Loading CE catalog...")
        : catalog.state === "error" ? catalog.error : t("{count} CEs selected", { count: names.length }));
    if (focusedGalleryName && !controls.disabled) {
      const galleryCard = [...galleryGrid.querySelectorAll("[data-equip-gallery-item]")]
        .find((btn) => btn.dataset.equipGalleryItem === focusedGalleryName && !btn.disabled);
      galleryCard?.focus({ preventScroll: true });
    } else if (focusedRow && !controls.disabled) {
      const rows = [...list.children];
      const replacement = rows.find((row) => row.dataset.assistEquipName === focusedRow.dataset.assistEquipName)
        || rows[Math.min(focusedIndex, rows.length - 1)];
      (replacement?.querySelector("button") || [add, refresh, clear].find((button) => !button.disabled)
        || section.querySelector("summary")).focus();
    } else if (focused === add && add.disabled && !controls.disabled) {
      (list.lastElementChild?.querySelector("button") || section.querySelector("summary")).focus();
    }
  }

  function change(action, name = picker.value) {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || editor.saving || editor.strategyApplyBusy) return;
    try {
      const info = inspectAssistEquipSource(source.value);
      if (action === "clear") {
        if (clear.disabled || !info.canClear || !window.confirm(t("Clear all assist CEs?"))) return;
      } else {
        if (info.error) throw new Error(info.error);
        const names = info.names;
        if (action === "add") {
          if (!editor.equipCatalog?.names?.includes(name) || names.includes(name)) return;
        } else if (!names.includes(name)) return;
      }
      source.value = editAssistEquipSource(source.value, { type: action, name });
      onChange();
    } catch (error) {
      onError(t(error.message));
    }
  }

  add.addEventListener("click", () => {
    if (!add.disabled) change("add");
  });
  picker.addEventListener("change", () => {
    picker.title = picker.selectedOptions[0]?.textContent || "";
    visualPicker.sync();
  });
  clear.addEventListener("click", () => change("clear"));
  refresh.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || refresh.disabled) return;
    editor.equipCatalog = null;
    render();
  });
  document.addEventListener("bbchannel:localechange", () => {
    galleryTitle.textContent = t("Click CE card to toggle");
    gallerySearch.placeholder = t("Filter CEs...");
    const emptyEl = galleryGrid.querySelector(".preset-equip-gallery-empty");
    if (emptyEl) emptyEl.textContent = t("No CE templates matched.");
    visualPicker.sync();
  });
  return { render };
}
