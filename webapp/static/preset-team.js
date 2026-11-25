import { t } from "./i18n.js";
import { editTeamSource, editUsedServantsSource, inspectTeamSource } from "./team-source.js";
import { createVisualSelect } from "./visual-select.js";

const STANDARD_CLASSES = new Set([
  "Saber", "Archer", "Lancer", "Rider", "Caster", "Assassin", "Berserker",
]);

function servantPortraitUrl(name, server, faceIndex = null) {
  const params = new URLSearchParams({ name, server: server || "CH" });
  if (Number.isInteger(faceIndex) && faceIndex > 0) {
    params.set("face", String(faceIndex));
  }
  return `/api/servants/image?${params.toString()}`;
}

function masterPortraitUrl(sn, sex = 0) {
  const params = new URLSearchParams({ equip: String(sn), sex: String(sex === 1 ? 1 : 0) });
  return `/api/masters/image?${params.toString()}`;
}

function skillIconUrl(iconName) {
  return `/api/skills/icon?name=${encodeURIComponent(iconName)}`;
}

export function createPresetTeamEditor({ getEditor, source, request, onChange, onError }) {
  const section = document.querySelector("#preset-team");
  const controls = document.querySelector("#preset-team-controls");
  const serverSelect = document.querySelector("#preset-server");
  const slots = [...document.querySelectorAll("[data-team-slot]")];
  const assistSlot = document.querySelector("#preset-assist-slot");
  const status = document.querySelector("#preset-team-status");
  const retry = document.querySelector("#retry-team-catalog");
  const master = document.querySelector("#preset-master-equip");
  const masterSex = document.querySelector("#preset-master-sex");
  const masterPreview = document.querySelector("#preset-master-preview");
  const masterPortrait = document.querySelector("#preset-master-portrait");
  const portraitStatus = document.querySelector("#preset-master-portrait-status");
  const portraitRetry = document.querySelector("#retry-master-portrait");
  const masterStatus = document.querySelector("#preset-master-status");
  const masterRetry = document.querySelector("#retry-master-catalog");
  const usedSlots = [...document.querySelectorAll("[data-team-used]")];
  const usedStatus = document.querySelector("#preset-used-status");

  function findServantEntry(servants, rawName) {
    if (!rawName || !Array.isArray(servants)) return null;
    return servants.find((s) => s.name === rawName)
      || servants.find((s) => Array.isArray(s.aliases) && s.aliases.includes(rawName))
      || null;
  }

  function currentTeamServer() {
    const editor = getEditor();
    const catServer = editor?.teamCatalog?.server;
    if (catServer) return catServer;
    const raw = serverSelect?.value || "CH";
    return ["CH", "CNTW", "JP"].includes(raw) ? raw : "CH";
  }

  const slotVisualSelects = slots.map((select) => createVisualSelect(select, {
    kind: "servant",
    showInlineThumb: true,
    minPopoverWidth: 360,
    getSearchPlaceholder: () => t("Search name or nickname (e.g. 光狐, 术呆, 摩根)..."),
    getEmptyText: () => t("No servants match the current filters."),
    getInlineThumb: () => {
      const val = select.value;
      if (!val) return { url: "", isNone: true };
      const servants = getEditor()?.teamCatalog?.servants || [];
      const info = findServantEntry(servants, val);
      const server = currentTeamServer();
      return {
        url: servantPortraitUrl(info?.name || val, server, info?.face_index),
        isNone: false,
      };
    },
    getFilters: () => [
      {
        key: "star",
        label: t("Rarity"),
        defaultValue: "all",
        options: [
          { value: "all", label: t("All") },
          { value: "5", label: "5★" },
          { value: "4", label: "4★" },
          { value: "3", label: "3★" },
          { value: "low", label: "≤2★" },
        ],
        predicate: (item, val) => {
          if (item.isNone) return true;
          const star = item.filterMeta?.star;
          if (typeof star !== "number") return false;
          if (val === "low") return star >= 0 && star <= 2;
          return star === Number(val);
        },
      },
      {
        key: "class",
        label: t("Class"),
        defaultValue: "all",
        options: [
          { value: "all", label: t("All") },
          { value: "Saber", label: t("Saber") },
          { value: "Archer", label: t("Archer") },
          { value: "Lancer", label: t("Lancer") },
          { value: "Rider", label: t("Rider") },
          { value: "Caster", label: t("Caster") },
          { value: "Assassin", label: t("Assassin") },
          { value: "Berserker", label: t("Berserker") },
          { value: "Extra", label: t("Extra") },
        ],
        predicate: (item, val) => {
          if (item.isNone) return true;
          const cls = item.filterMeta?.class;
          if (!cls) return false;
          if (val === "Extra") return !STANDARD_CLASSES.has(cls);
          return cls === val;
        },
      },
    ],
    getItems: () => {
      const servants = getEditor()?.teamCatalog?.servants || [];
      const byName = new Map(servants.map((s) => [s.name, s]));
      const server = currentTeamServer();
      return [...select.options].map((opt) => {
        if (opt.value === "" && !opt.disabled) {
          return {
            value: "",
            label: opt.textContent || t("None"),
            isNone: true,
            thumbKind: "servant",
          };
        }
        const info = byName.get(opt.value) || findServantEntry(servants, opt.value);
        const badges = [];
        if (typeof info?.star === "number") {
          badges.push({ text: `${info.star}★`, className: `star-${info.star}` });
        }
        if (info?.np_color) {
          badges.push({ text: info.np_color, className: `np-${String(info.np_color).toLowerCase()}` });
        }
        if (info?.class) {
          badges.push({ text: t(info.class), className: "class-tag" });
        }
        const aliases = Array.isArray(info?.aliases) ? info.aliases.filter(Boolean) : [];
        return {
          value: opt.value,
          label: opt.textContent || opt.value,
          disabled: opt.disabled,
          imageUrl: opt.value ? servantPortraitUrl(info?.name || opt.value, server, info?.face_index) : "",
          thumbKind: "servant",
          badges,
          subtitle: aliases.slice(0, 4).join(" / "),
          searchText: `${info?.class || ""} ${aliases.join(" ")}`,
          filterMeta: { star: info?.star, class: info?.class },
        };
      });
    },
  }));

  const masterVisualSelect = createVisualSelect(master, {
    kind: "master",
    showInlineThumb: false,
    minPopoverWidth: 380,
    getSearchPlaceholder: () => t("Search master outfits or skills (e.g. Order Change, NP)..."),
    getEmptyText: () => t("No outfits match the current search."),
    getItems: () => {
      const masters = getEditor()?.masterCatalog?.masters || [];
      const bySn = new Map(masters.map((m) => [String(m.sn), m]));
      const sex = masterSex.value === "1" ? 1 : 0;
      return [...master.options].map((opt) => {
        if (opt.value === "" && !opt.disabled) {
          return {
            value: "",
            label: opt.textContent || t("None"),
            isNone: true,
            thumbKind: "master",
          };
        }
        const info = bySn.get(opt.value);
        const badges = [];
        if (Array.isArray(info?.skill_types) && info.skill_types.includes(2)) {
          badges.push({ text: t("Order Change"), className: "swap-tag" });
        }
        const skillIcons = [];
        const skillSearchParts = [];
        for (let i = 0; i < 3; i += 1) {
          const iconKey = typeof info?.skills?.[i] === "string" ? info.skills[i].trim() : "";
          const detailObj = info?.skill_details?.[i];
          const skName = typeof detailObj?.name === "string" ? detailObj.name.trim() : "";
          const skDetail = typeof detailObj?.detail === "string" ? detailObj.detail.trim() : "";
          const shortLabel = skName || iconKey;
          if (iconKey || shortLabel) {
            skillIcons.push({
              url: iconKey ? skillIconUrl(iconKey) : "",
              label: shortLabel,
              tooltip: skDetail ? `${shortLabel}: ${skDetail}` : shortLabel,
            });
          }
          if (iconKey) skillSearchParts.push(iconKey);
          if (skName) skillSearchParts.push(skName);
          if (skDetail) skillSearchParts.push(skDetail);
        }
        if (Array.isArray(info?.skill_types) && info.skill_types.includes(2)) {
          skillSearchParts.push("换人 order change swap");
        }
        return {
          value: opt.value,
          label: opt.textContent || opt.value,
          disabled: opt.disabled,
          imageUrl: info ? masterPortraitUrl(info.sn, sex) : "",
          thumbKind: "master",
          badges,
          skillIcons,
          searchText: skillSearchParts.join(" "),
        };
      });
    },
  });

  function syncVisualControls() {
    slotVisualSelects.forEach((v) => v.sync());
    masterVisualSelect.sync();
  }

  function closeVisualControls() {
    slotVisualSelects.forEach((v) => v.close());
    masterVisualSelect.close();
  }

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error(t("Invalid script JSON."));
    return config;
  }

  function option(value, label, disabled = false) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    item.disabled = disabled;
    return item;
  }

  function renderServer(config) {
    serverSelect.querySelector("option[data-current]")?.remove();
    const value = config.server;
    const normalized = typeof value === "string" ? value.toUpperCase() : "";
    if (value === undefined) {
      serverSelect.value = "";
    } else if (["CH", "CNTW", "JP"].includes(normalized)) {
      serverSelect.value = normalized;
    } else {
      const current = option("", t("{name} (current)", { name: JSON.stringify(value) }), true);
      current.dataset.current = "";
      serverSelect.append(current);
      serverSelect.selectedIndex = serverSelect.options.length - 1;
    }
    serverSelect.title = serverSelect.selectedOptions[0]?.textContent || "";
  }

  function renderSlots(config, catalog) {
    const servants = catalog?.servants || [];
    slots.forEach((select) => {
      const value = config[`servant_${select.dataset.teamSlot}_name`];
      const options = [option("", t("None")), ...servants.map((servant) => option(servant.name, servant.name))];
      if (typeof value === "string" && value && !servants.some((servant) => servant.name === value)) {
        const canonical = servants.find((servant) => servant.aliases?.includes(value));
        options.push(option(value, canonical ? `${value} (${canonical.name})` : t("{name} (current)", { name: value })));
      }
      const invalid = value !== undefined && typeof value !== "string";
      if (invalid) options.push(option("", t(value === null ? "Null (current)" : "Invalid name"), true));
      select.replaceChildren(...options);
      if (invalid) select.selectedIndex = options.length - 1;
      else select.value = value || "";
      select.title = select.selectedOptions[0]?.textContent || "";
      select.disabled = catalog?.state !== "ready";
    });
    const value = config.assistIdx;
    const options = [option("", t("Not set")), ...slots.map((_, index) => option(String(index), t("Slot {slot}", { slot: index + 1 })))];
    const invalid = value !== undefined && (!Number.isInteger(value) || value < 0 || value > 5);
    if (invalid) options.push(option("", t(value === null ? "Null (current)" : "Invalid slot"), true));
    assistSlot.replaceChildren(...options);
    if (invalid) assistSlot.selectedIndex = options.length - 1;
    else assistSlot.value = value == null ? "" : String(value);
    assistSlot.title = assistSlot.selectedOptions[0]?.textContent || "";
  }

  async function loadCatalog(editor, catalog) {
    try {
      const payload = await request(`/api/servants?server=${encodeURIComponent(catalog.server)}`);
      if (payload.server !== catalog.server || !Array.isArray(payload.servants)
          || payload.servants.some((servant) => !servant || typeof servant.name !== "string" || !servant.name)) {
        throw new Error(t("Invalid servant catalog."));
      }
      catalog.servants = payload.servants;
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || t("Servant catalog unavailable.");
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
        throw new Error(t("Invalid master outfit catalog."));
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
      catalog.error = error.message || t("Master outfit catalog unavailable.");
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
    const options = [option("", t("None")), ...masters.map((item) => option(String(item.sn), item.name))];
    const current = value !== undefined && !selected;
    if (current) options.push(option("", t("{name} (current)", { name: JSON.stringify(value) }), true));
    master.replaceChildren(...options);
    if (current) master.selectedIndex = options.length - 1;
    else master.value = selected ? String(selected.sn) : "";
    master.title = master.selectedOptions[0]?.textContent || "";
    master.disabled = catalog.state !== "ready";
    masterRetry.hidden = catalog.state !== "error";
    masterStatus.textContent = catalog.state === "loading" ? t("Loading master outfits...")
      : catalog.state === "error" ? catalog.error
        : masters.length ? t("{count} outfits", { count: masters.length }) : t("No outfits available");
  }

  function renderUsed(state, ambiguous) {
    usedSlots.forEach((input) => {
      input.checked = state.valid && state.slots.includes(Number(input.dataset.teamUsed));
      input.disabled = !state.valid;
      input.title = ambiguous ? t("Ambiguous team field.") : "";
    });
    usedStatus.textContent = ambiguous ? t("Ambiguous team field.")
      : !state.valid ? t("Invalid usedServant value.")
        : state.unrecognized ? t("Unrecognized entries retained.") : "";
    usedStatus.hidden = !usedStatus.textContent;
  }

  function protectAmbiguous(editor, fields) {
    const ambiguous = new Set(fields);
    const selections = [[serverSelect, "server", false], [masterSex, "master_sex", false],
      [assistSlot, "assistIdx", false], [master, "master_equip", editor.masterCatalog?.state !== "ready"],
      ...slots.map((select) => [select, `servant_${select.dataset.teamSlot}_name`, editor.teamCatalog?.state !== "ready"])];
    for (const [select, field, unavailable] of selections) {
      select.disabled = unavailable || ambiguous.has(field);
      if (ambiguous.has(field)) select.title = t("Ambiguous team field.");
    }
  }

  function renderMasterSex(config) {
    const value = config.master_sex;
    const options = [option("0", t("Female")), option("1", t("Male"))];
    const current = value !== undefined && value !== 0 && value !== 1;
    if (current) options.push(option("", t("{name} (current)", { name: JSON.stringify(value) }), true));
    masterSex.replaceChildren(...options);
    if (current) masterSex.selectedIndex = options.length - 1;
    else masterSex.value = String(value === undefined ? 0 : value);
    masterSex.title = masterSex.selectedOptions[0]?.textContent || "";
  }

  function renderMasterPortrait(config, editor, reload = false) {
    const catalog = editor.masterCatalog;
    const selected = catalog?.state === "ready" && validMasterId(config.master_equip)
      ? catalog.masters.find((item) => String(item.sn) === String(config.master_equip)) : null;
    const sex = config.master_sex === undefined ? 0 : config.master_sex;
    const key = selected && (sex === 0 || sex === 1) ? JSON.stringify([selected.sn, selected.name, sex]) : null;
    if (!reload && editor.masterPortrait?.key === key) return;
    const view = { key };
    editor.masterPortrait = view;
    masterPreview.hidden = key === null;
    masterPortrait.replaceChildren();
    portraitStatus.textContent = "";
    portraitRetry.hidden = true;
    if (key === null) return;
    const image = document.createElement("img");
    image.width = image.height = 50;
    image.alt = t("Master portrait");
    portraitStatus.textContent = t("Loading portrait...");
    const current = () => getEditor() === editor && editor.masterPortrait === view;
    image.addEventListener("load", () => {
      if (current()) portraitStatus.textContent = "";
    });
    image.addEventListener("error", () => {
      if (!current()) return;
      image.hidden = true;
      portraitStatus.textContent = t("Preview unavailable");
      portraitRetry.hidden = false;
    });
    image.src = `/api/masters/image?${new URLSearchParams({ equip: String(selected.sn), sex: String(sex) })}`;
    masterPortrait.append(image);
  }

  function render() {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") {
      closeVisualControls();
      return;
    }
    if (!editor.teamInitialized) {
      section.open = false;
      editor.teamInitialized = true;
    }
    retry.hidden = true;
    let config;
    let info;
    try {
      config = readConfig();
      info = inspectTeamSource(source.value);
    } catch {
      editor.teamCatalog = null;
      controls.disabled = true;
      status.textContent = t("Invalid script JSON.");
      masterStatus.textContent = t("Invalid script JSON.");
      usedStatus.textContent = t("Invalid script JSON.");
      usedStatus.hidden = false;
      masterRetry.hidden = true;
      editor.masterPortrait = null;
      masterPreview.hidden = true;
      masterPortrait.replaceChildren();
      syncVisualControls();
      return;
    }
    renderServer(config);
    renderMasters(config, editor);
    renderMasterSex(config);
    renderMasterPortrait(config, editor);
    renderUsed(info.used, info.ambiguous.includes("usedServant"));
    const server = typeof config.server === "string" ? config.server.toUpperCase() : "";
    if (!["CH", "CNTW", "JP"].includes(server)) {
      editor.teamCatalog = null;
      renderSlots(config, null);
      status.textContent = t("Unsupported server.");
      protectAmbiguous(editor, info.ambiguous);
      syncVisualControls();
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
    status.textContent = catalog.state === "loading" ? t("Loading {server} servants...", { server })
      : catalog.state === "error" ? catalog.error
        : t("{count} servants ({server})", { count: catalog.servants.length, server });
    protectAmbiguous(editor, info.ambiguous);
    syncVisualControls();
  }

  function update(event) {
    const editor = getEditor();
    const select = event.currentTarget;
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy
        || controls.disabled || select.disabled || select.selectedOptions[0]?.disabled) return;
    try {
      let field;
      let value;
      let removing = false;
      if (select === serverSelect) {
        field = "server";
        removing = select.value === "";
        value = select.value;
      } else if (select === master) {
        field = "master_equip";
        removing = select.value === "";
        if (!removing) {
          const selected = editor.masterCatalog?.masters?.find((item) => String(item.sn) === select.value);
          if (!selected) return;
          value = selected.sn;
        }
      } else if (select === masterSex) {
        if (!["0", "1"].includes(select.value)) return;
        field = "master_sex";
        value = Number(select.value);
      } else if (select === assistSlot) {
        field = "assistIdx";
        removing = select.value === "";
        value = Number(select.value);
      } else {
        field = `servant_${select.dataset.teamSlot}_name`;
        value = select.value;
      }
      source.value = editTeamSource(source.value, { type: removing ? "remove" : "set", field, value });
      onChange(select === serverSelect ? "server" : undefined);
    } catch (error) {
      onError(t(error.message));
    }
  }

  function updateUsed(event) {
    const editor = getEditor();
    const input = event.currentTarget;
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy
        || controls.disabled || input.disabled) return;
    try {
      const slot = Number(input.dataset.teamUsed);
      source.value = editUsedServantsSource(source.value, slot, input.checked);
      onChange();
    } catch (error) {
      onError(t(error.message));
    }
  }

  slots.forEach((select) => select.addEventListener("change", update));
  serverSelect.addEventListener("change", update);
  usedSlots.forEach((input) => input.addEventListener("change", updateUsed));
  assistSlot.addEventListener("change", update);
  master.addEventListener("change", update);
  masterSex.addEventListener("change", update);
  portraitRetry.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || editor.saving || editor.strategyApplyBusy) return;
    try {
      renderMasterPortrait(readConfig(), editor, true);
    } catch (error) {
      onError(error.message);
    }
  });
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
