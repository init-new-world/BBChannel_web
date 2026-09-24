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

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error("Invalid script JSON.");
    return config;
  }

  function equipNames(value) {
    const names = new Set();
    const pending = [value];
    let visited = 0;
    while (pending.length) {
      if (++visited > 1000) throw new Error("CE list exceeds 1,000 values.");
      const item = pending.pop();
      if (item == null) continue;
      if (typeof item === "string") {
        if (item) names.add(item);
      } else if (Array.isArray(item)) {
        if (visited + pending.length + item.length > 1000) throw new Error("CE list exceeds 1,000 values.");
        for (let index = item.length - 1; index >= 0; index--) pending.push(item[index]);
      } else {
        throw new Error("Unsupported CE value.");
      }
    }
    return [...names];
  }

  function removeName(value, name) {
    if (!Array.isArray(value)) return value === name ? [] : value;
    return value.filter((item) => item !== name).map((item) => removeName(item, name));
  }

  async function loadCatalog(editor, catalog) {
    try {
      const payload = await request("/api/equip-templates");
      if (!Array.isArray(payload.templates) || payload.templates.some((item) => !item || typeof item.name !== "string")) {
        throw new Error("Invalid CE catalog.");
      }
      catalog.names = [...new Set(payload.templates.filter((item) => item.location === "active" && item.name).map((item) => item.name))];
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || "CE catalog unavailable.";
    }
    if (getEditor() === editor && editor.equipCatalog === catalog) {
      const restoreFocus = catalog.restoreRefreshFocus && document.activeElement === document.body;
      render();
      if (restoreFocus && !controls.disabled && !refresh.disabled) refresh.focus();
    }
  }

  function equipRow(name, available) {
    const row = document.createElement("div");
    row.className = "preset-equip-row";
    row.dataset.assistEquipName = name;
    const thumbnail = document.createElement("div");
    thumbnail.className = "preset-equip-thumbnail";
    const caption = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = name;
    const note = document.createElement("small");
    note.textContent = available === false ? "Unavailable" : "";
    note.hidden = available !== false;
    caption.append(label, note);
    if (available) {
      const image = document.createElement("img");
      image.alt = "";
      image.width = 88;
      image.height = 26;
      image.src = `/api/equip-templates/${encodeURIComponent(name)}/image?location=active`;
      image.addEventListener("error", () => {
        image.hidden = true;
        note.hidden = false;
        note.textContent = "Preview unavailable";
      });
      thumbnail.append(image);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button";
    button.title = "Remove CE";
    button.setAttribute("aria-label", "Remove CE");
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
    let config;
    try {
      config = readConfig();
    } catch {
      controls.disabled = true;
      status.textContent = "Invalid script JSON.";
      return;
    }
    let catalog = editor.equipCatalog;
    if (!catalog) {
      catalog = { state: "loading", restoreRefreshFocus: document.activeElement === refresh };
      editor.equipCatalog = catalog;
      void loadCatalog(editor, catalog);
    }
    let names = [];
    let error = "";
    try {
      names = equipNames(config.assistEquip);
    } catch (failure) {
      error = failure.message;
    }
    const focused = document.activeElement;
    const focusedRow = focused?.closest("[data-assist-equip-name]");
    const focusedIndex = [...list.children].indexOf(focusedRow);
    const available = catalog.names || [];
    list.replaceChildren(...names.map((name) => equipRow(name, catalog.state === "ready" ? available.includes(name) : null)));
    const choices = available.filter((name) => !names.includes(name));
    const selected = picker.value;
    picker.replaceChildren(...(choices.length ? choices : [""]).map((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name || "No unused active CEs";
      return option;
    }));
    if (choices.includes(selected)) picker.value = selected;
    picker.title = picker.selectedOptions[0]?.textContent || "";
    picker.disabled = Boolean(error) || catalog.state !== "ready" || !choices.length;
    add.disabled = picker.disabled;
    clear.disabled = !Object.hasOwn(config, "assistEquip") || (Array.isArray(config.assistEquip) && !config.assistEquip.length);
    refresh.disabled = catalog.state === "loading";
    status.textContent = error || (!usesEquip ? "Inactive for this recognition mode."
      : catalog.state === "loading" ? "Loading CE catalog..."
        : catalog.state === "error" ? catalog.error : `${names.length} CEs selected`);
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
      const config = readConfig();
      if (action === "clear") {
        if (clear.disabled || !window.confirm("Clear all assist CEs?")) return;
        config.assistEquip = [];
      } else {
        const names = equipNames(config.assistEquip);
        if (action === "add") {
          if (add.disabled || !editor.equipCatalog?.names?.includes(name) || names.includes(name)) return;
          const current = config.assistEquip;
          const next = Array.isArray(current) ? [...current, name] : current ? [current, name] : [name];
          equipNames(next);
          config.assistEquip = next;
        } else if (names.includes(name)) {
          config.assistEquip = removeName(config.assistEquip, name);
        } else return;
      }
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
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
