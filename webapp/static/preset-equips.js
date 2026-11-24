import { t } from "./i18n.js";
import { editAssistEquipSource, inspectAssistEquipGrandSlots, inspectAssistEquipSource } from "./assist-equips-source.js";

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
      image.src = `/api/equip-templates/${encodeURIComponent(name)}/image?location=active`;
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

  function render(enabled = usesEquip) {
    usesEquip = Boolean(enabled);
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || !usesEquip || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") return;
    if (!editor.equipsInitialized) {
      section.open = false;
      editor.equipsInitialized = true;
    }
    let info;
    try {
      info = inspectAssistEquipSource(source.value);
    } catch (error) {
      controls.disabled = true;
      list.replaceChildren();
      status.textContent = t(error.message);
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
    status.textContent = error || (!usesEquip ? t("Inactive for this recognition mode.")
      : catalog.state === "loading" ? t("Loading CE catalog...")
        : catalog.state === "error" ? catalog.error : t("{count} CEs selected", { count: names.length }));
    if (focusedRow && !controls.disabled) {
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
          if (add.disabled || !editor.equipCatalog?.names?.includes(name) || names.includes(name)) return;
        } else if (!names.includes(name)) return;
      }
      source.value = editAssistEquipSource(source.value, { type: action, name });
      onChange();
    } catch (error) {
      onError(t(error.message));
    }
  }

  add.addEventListener("click", () => change("add"));
  picker.addEventListener("change", () => { picker.title = picker.selectedOptions[0]?.textContent || ""; });
  clear.addEventListener("click", () => change("clear"));
  refresh.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || refresh.disabled) return;
    editor.equipCatalog = null;
    render();
  });
  return { render };
}
