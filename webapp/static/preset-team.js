export function createPresetTeamEditor({ getEditor, source, request, onChange, onError }) {
  const section = document.querySelector("#preset-team");
  const controls = document.querySelector("#preset-team-controls");
  const slots = [...document.querySelectorAll("[data-team-slot]")];
  const assistSlot = document.querySelector("#preset-assist-slot");
  const status = document.querySelector("#preset-team-status");
  const retry = document.querySelector("#retry-team-catalog");
  const master = document.querySelector("#preset-master-equip");
  const masterStatus = document.querySelector("#preset-master-status");
  const masterRetry = document.querySelector("#retry-master-catalog");

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error("Invalid script JSON.");
    return config;
  }

  function option(value, label, disabled = false) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    item.disabled = disabled;
    return item;
  }

  function renderSlots(config, catalog) {
    const servants = catalog?.servants || [];
    slots.forEach((select) => {
      const value = config[`servant_${select.dataset.teamSlot}_name`];
      const options = [option("", "None"), ...servants.map((servant) => option(servant.name, servant.name))];
      if (typeof value === "string" && value && !servants.some((servant) => servant.name === value)) {
        const canonical = servants.find((servant) => servant.aliases?.includes(value));
        options.push(option(value, canonical ? `${value} (${canonical.name})` : `${value} (current)`));
      }
      const invalid = value !== undefined && typeof value !== "string";
      if (invalid) options.push(option("", value === null ? "Null (current)" : "Invalid name", true));
      select.replaceChildren(...options);
      if (invalid) select.selectedIndex = options.length - 1;
      else select.value = value || "";
      select.title = select.selectedOptions[0]?.textContent || "";
      select.disabled = catalog?.state !== "ready";
    });
    const value = config.assistIdx;
    const options = [option("", "Not set"), ...slots.map((_, index) => option(String(index), `Slot ${index + 1}`))];
    const invalid = value !== undefined && (!Number.isInteger(value) || value < 0 || value > 5);
    if (invalid) options.push(option("", value === null ? "Null (current)" : "Invalid slot", true));
    assistSlot.replaceChildren(...options);
    if (invalid) assistSlot.selectedIndex = options.length - 1;
    else assistSlot.value = value == null ? "" : String(value);
  }

  async function loadCatalog(editor, catalog) {
    try {
      const payload = await request(`/api/servants?server=${encodeURIComponent(catalog.server)}`);
      if (payload.server !== catalog.server || !Array.isArray(payload.servants)
          || payload.servants.some((servant) => !servant || typeof servant.name !== "string" || !servant.name)) {
        throw new Error("Invalid servant catalog.");
      }
      catalog.servants = payload.servants;
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || "Servant catalog unavailable.";
    }
    // Both identities matter when a server changes A -> B -> A or an editor is reopened.
    if (getEditor() === editor && editor.teamCatalog === catalog) render();
  }

  function validMasterId(value) {
    return (typeof value === "string" && value !== "") || Number.isSafeInteger(value);
  }

  async function loadMasters(editor, catalog) {
    try {
      const payload = await request("/api/masters");
      if (!Array.isArray(payload.masters) || payload.masters.some((item) => !item
          || typeof item.name !== "string" || !item.name || !validMasterId(item.sn))) {
        throw new Error("Invalid master outfit catalog.");
      }
      const seen = new Set();
      catalog.masters = payload.masters.filter((item) => {
        const key = String(item.sn);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || "Master outfit catalog unavailable.";
    }
    if (getEditor() === editor && editor.masterCatalog === catalog) {
      const restoreFocus = catalog.restoreFocus && document.activeElement === document.body;
      render();
      if (restoreFocus && !controls.disabled) (catalog.state === "ready" ? master : masterRetry).focus();
    }
  }

  function renderMasters(config, editor) {
    let catalog = editor.masterCatalog;
    if (!catalog) {
      catalog = { state: "loading", restoreFocus: document.activeElement === masterRetry };
      editor.masterCatalog = catalog;
      void loadMasters(editor, catalog);
    }
    const masters = catalog.masters || [];
    const value = config.master_equip;
    const selected = validMasterId(value) ? masters.find((item) => String(item.sn) === String(value)) : null;
    const options = [option("", "None"), ...masters.map((item) => option(String(item.sn), item.name))];
    const current = value !== undefined && !selected;
    if (current) options.push(option("", `${JSON.stringify(value)} (current)`, true));
    master.replaceChildren(...options);
    if (current) master.selectedIndex = options.length - 1;
    else master.value = selected ? String(selected.sn) : "";
    master.title = master.selectedOptions[0]?.textContent || "";
    master.disabled = catalog.state !== "ready";
    masterRetry.hidden = catalog.state !== "error";
    masterStatus.textContent = catalog.state === "loading" ? "Loading master outfits..."
      : catalog.state === "error" ? catalog.error
        : masters.length ? `${masters.length} outfits` : "No outfits available";
  }

  function render() {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") return;
    if (!editor.teamInitialized) {
      section.open = false;
      editor.teamInitialized = true;
    }
    retry.hidden = true;
    let config;
    try {
      config = readConfig();
    } catch {
      editor.teamCatalog = null;
      controls.disabled = true;
      status.textContent = "Invalid script JSON.";
      masterStatus.textContent = "Invalid script JSON.";
      masterRetry.hidden = true;
      return;
    }
    renderMasters(config, editor);
    const server = typeof config.server === "string" ? config.server.toUpperCase() : "";
    if (!["CH", "CNTW", "JP"].includes(server)) {
      editor.teamCatalog = null;
      renderSlots(config, null);
      status.textContent = "Unsupported server.";
      return;
    }
    let catalog = editor.teamCatalog;
    if (!catalog || catalog.server !== server) {
      catalog = { server, state: "loading" };
      editor.teamCatalog = catalog;
      void loadCatalog(editor, catalog);
    }
    renderSlots(config, catalog);
    retry.hidden = catalog.state !== "error";
    status.textContent = catalog.state === "loading" ? `Loading ${server} servants...`
      : catalog.state === "error" ? catalog.error
        : `${catalog.servants.length} servants (${server})`;
  }

  function update(event) {
    const editor = getEditor();
    const select = event.currentTarget;
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy
        || controls.disabled || select.disabled || select.selectedOptions[0]?.disabled) return;
    try {
      const config = readConfig();
      if (select === master) {
        if (select.value === "") delete config.master_equip;
        else {
          const selected = editor.masterCatalog?.masters?.find((item) => String(item.sn) === select.value);
          if (!selected) return;
          config.master_equip = selected.sn;
        }
      } else if (select === assistSlot) {
        if (select.value === "") delete config.assistIdx;
        else config.assistIdx = Number(select.value);
      } else {
        config[`servant_${select.dataset.teamSlot}_name`] = select.value;
      }
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
    }
  }

  slots.forEach((select) => select.addEventListener("change", update));
  assistSlot.addEventListener("change", update);
  master.addEventListener("change", update);
  masterRetry.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled) return;
    editor.masterCatalog = null;
    render();
  });
  retry.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled) return;
    editor.teamCatalog = null;
    render();
  });
  return { render };
}
