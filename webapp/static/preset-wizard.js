import { t } from "./i18n.js";
import {
  applyOrderChange,
  buildWizardSpecialCommand,
  computeLineupBefore,
  extractServantSkillNumber,
  formatSpecialSkillCommand,
  resolveWizardSpecialSkill,
} from "./wizard-special-skills.js";

const CLASS_GROUPS = [
  { key: "all", labelKey: "All" },
  { key: "Saber", labelKey: "Saber" },
  { key: "Archer", labelKey: "Archer" },
  { key: "Lancer", labelKey: "Lancer" },
  { key: "Rider", labelKey: "Rider" },
  { key: "Caster", labelKey: "Caster" },
  { key: "Assassin", labelKey: "Assassin" },
  { key: "Berserker", labelKey: "Berserker" },
  { key: "Extra", labelKey: "Extra" },
];

const STANDARD_CLASSES = new Set([
  "Saber", "Archer", "Lancer", "Rider", "Caster", "Assassin", "Berserker",
]);

const POPULAR_SUPPORT_NAMES = [
  "光之高扬斯卡娅",
  "阿尔托莉雅·Caster",
  "奥伯龙",
  "斯卡哈·斯卡蒂(Ruler)",
  "斯卡哈·斯卡蒂",
  "司马懿〔莱妮丝〕",
  "暗之高扬斯卡娅",
  "诸葛孔明〔埃尔梅罗Ⅱ世〕",
  "梅林",
  "阿瓦隆女士",
  "摩根",
  "库库尔坎",
];

const GRAND_MODES = new Set(["冠位助战", "冠位助战仅礼装"]);
const GRAND_SLOT_KEYS = ["normal", "kizuna", "houshuu"];

function safeParseConfig(sourceText) {
  try {
    const parsed = JSON.parse(sourceText);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  } catch {
    // Fall back to empty object if source is malformed.
  }
  return { server: "CH", round1_turns: 1 };
}

function servantPortraitUrl(name, server, faceIndex = null) {
  const params = new URLSearchParams({ name, server: server || "CH" });
  if (Number.isInteger(faceIndex) && faceIndex > 0) {
    params.set("face", String(faceIndex));
  }
  return `/api/servants/image?${params.toString()}`;
}

function masterPortraitUrl(sn, sex = 0) {
  const params = new URLSearchParams({ equip: String(sn), sex: String(sex ? 1 : 0) });
  return `/api/masters/image?${params.toString()}`;
}

function skillIconUrl(iconName) {
  return `/api/skills/icon?name=${encodeURIComponent(iconName)}`;
}

function resolveSkillDisplay(info, skillIndex, fallbackLabel) {
  const iconKey = typeof info?.skills?.[skillIndex] === "string" ? info.skills[skillIndex].trim() : "";
  const detailObj = info?.skill_details?.[skillIndex];
  const officialName = typeof detailObj?.name === "string" ? detailObj.name.trim() : "";
  const detailText = typeof detailObj?.detail === "string" ? detailObj.detail.trim() : "";
  return {
    iconKey,
    title: officialName || iconKey || fallbackLabel,
    note: detailText || (officialName && iconKey ? iconKey : ""),
  };
}

function collectFlatEquipNames(value) {
  const flat = [];
  const stack = [value];
  while (stack.length) {
    const item = stack.pop();
    if (typeof item === "string") {
      if (item && !flat.includes(item)) flat.push(item);
    } else if (Array.isArray(item)) {
      for (let i = item.length - 1; i >= 0; i -= 1) stack.push(item[i]);
    } else if (item && typeof item === "object") {
      const keys = [...GRAND_SLOT_KEYS, ...Object.keys(item).filter((k) => !GRAND_SLOT_KEYS.includes(k))];
      for (let i = keys.length - 1; i >= 0; i -= 1) {
        if (Object.hasOwn(item, keys[i])) stack.push(item[keys[i]]);
      }
    }
  }
  return flat;
}

function normalizeAssistEquipArray(value, isGrand, wasGrand = isGrand) {
  if (isGrand) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return GRAND_SLOT_KEYS.map((slotKey) => collectFlatEquipNames(value[slotKey]));
    }
    if (wasGrand && Array.isArray(value) && value.length === 3 && value.some((v) => v === null || Array.isArray(v))) {
      return value.map((slot) => collectFlatEquipNames(slot));
    }
    return [collectFlatEquipNames(value), [], []];
  }
  return collectFlatEquipNames(value);
}

function extractWaveCount(config) {
  let maxWave = 0;
  for (const key of Object.keys(config)) {
    const match = /^round(\d+)_/.exec(key);
    if (match) {
      maxWave = Math.max(maxWave, Number(match[1]));
    }
  }
  return Math.max(1, maxWave);
}

function hasWaveData(config, wave) {
  const prefix = `round${wave}_`;
  for (const [key, value] of Object.entries(config)) {
    if (!key.startsWith(prefix)) continue;
    const suffix = key.slice(prefix.length);
    if (suffix === "turns") {
      if (Number(value) > 1) return true;
      continue;
    }
    if (Array.isArray(value)) {
      if (value.length > 0) return true;
      continue;
    }
    if (typeof value === "string" && value.trim()) return true;
    if (typeof value === "number" && value !== 0) return true;
    if (typeof value === "boolean" && value) return true;
    if (value && typeof value === "object" && Object.keys(value).length > 0) return true;
  }
  return false;
}

function removeWaveFromConfig(draft, targetWave) {
  const shifted = [];
  for (const key of Object.keys(draft)) {
    const match = /^round(\d+)_(.+)$/.exec(key);
    if (!match) continue;
    const roundNum = Number(match[1]);
    if (roundNum === targetWave) {
      delete draft[key];
    } else if (roundNum > targetWave) {
      shifted.push([roundNum, match[2], draft[key]]);
      delete draft[key];
    }
  }
  shifted.sort((a, b) => a[0] - b[0]);
  for (const [roundNum, suffix, value] of shifted) {
    draft[`round${roundNum - 1}_${suffix}`] = value;
  }
  if (!Object.keys(draft).some((k) => k.startsWith("round1_"))) {
    draft.round1_turns = 1;
    draft.round1_turn0_skill = [];
    draft.round1_turn0_np = [];
  }
}

function buildSuggestedName(config) {
  const names = [];
  for (let i = 0; i < 3; i += 1) {
    const raw = config[`servant_${i}_name`];
    if (typeof raw === "string" && raw.trim()) {
      names.push(raw.trim().slice(0, 12));
    }
  }
  if (!names.length) return "";
  const suffix = GRAND_MODES.has(config.assistMode) ? "_冠位" : "";
  return `${names.join("_")}${suffix}`;
}

function createAvatarImg(src, alt, className = "wizard-avatar") {
  const img = document.createElement("img");
  img.className = className;
  img.alt = alt || "";
  img.loading = "lazy";
  img.src = src;
  img.addEventListener("error", () => {
    img.classList.add("broken");
  });
  return img;
}

export function createPresetWizard({
  root,
  getEditor,
  source,
  nameInput,
  request,
  getStrategies,
  onChange,
  onSwitchToPro,
}) {
  const state = {
    step: 0,
    activeSlot: 0,
    starFilter: "all",
    classFilter: "all",
    npFilter: "all",
    searchQuery: "",
    masterSearchQuery: "",
    masterFilter: "all",
    ceSearchQuery: "",
    grandCeSlot: 0,
    activeWave: 1,
    pendingTargetSkill: null, // { skillNum, isSwap, label }
    servantsByServer: new Map(),
    servantsError: new Map(),
    masters: null,
    mastersError: false,
    equips: null,
    equipsLoading: false,
    equipsError: false,
    loadingServer: null,
    autoNamedValue: "",
  };

  function readConfig() {
    return safeParseConfig(source.value);
  }

  function writeConfig(mutator, { rerender = true } = {}) {
    const config = readConfig();
    mutator(config);
    source.value = JSON.stringify(config, null, 2);
    onChange();
    if (rerender) render();
  }

  function ensureWizardDefaultsForNewScript() {
    const editor = getEditor();
    if (!editor || editor.wizardDefaultsApplied || editor.originalName) return;
    editor.wizardDefaultsApplied = true;
    const config = readConfig();
    const hasAnyServant = [0, 1, 2, 3, 4, 5].some((i) => Boolean(config[`servant_${i}_name`]));
    const hasRounds = Object.keys(config).some((k) => /^round[23]_/.test(k));
    if (!hasAnyServant && !hasRounds && (config.round1_turns === 0 || config.round1_turns === undefined)) {
      writeConfig((draft) => {
        draft.server = draft.server || "CH";
        draft.assistMode = draft.assistMode || "从者礼装";
        draft.assistIdx = draft.assistIdx ?? 2;
        draft.fullEquip = draft.fullEquip ?? 1;
        draft.onlyFriendAssist = draft.onlyFriendAssist ?? 0;
        draft.NPlevel = draft.NPlevel ?? 1;
        draft.servantLevel = draft.servantLevel ?? 1;
        draft.skillsLevel = Array.isArray(draft.skillsLevel) ? draft.skillsLevel : [10, 10, 10, 0, 0, 0, 0, 0];
        draft.fullFriendshipStop = draft.fullFriendshipStop ?? 1;
        draft.gameCrushRestart = draft.gameCrushRestart ?? 1;
        draft.firstBattleSet = draft.firstBattleSet ?? 1;
        draft.allowOtherApple = draft.allowOtherApple ?? 1;
        draft.clearAP = draft.clearAP ?? 0;
        draft.round1_turns = 1;
        draft.round2_turns = 1;
        draft.round3_turns = 1;
        draft.round1_turn0_skill = draft.round1_turn0_skill || [];
        draft.round1_turn0_np = draft.round1_turn0_np || [];
        draft.round2_turn0_skill = draft.round2_turn0_skill || [];
        draft.round2_turn0_np = draft.round2_turn0_np || [];
        draft.round3_turn0_skill = draft.round3_turn0_skill || [];
        draft.round3_turn0_np = draft.round3_turn0_np || [];
      }, { rerender: false });
    }
  }

  async function ensureCatalogs(server) {
    const normalizedServer = ["CH", "CNTW", "JP"].includes(String(server || "").toUpperCase())
      ? String(server).toUpperCase()
      : "CH";
    const promises = [];
    if (!state.servantsByServer.has(normalizedServer) && state.loadingServer !== normalizedServer && !state.servantsError.get(normalizedServer)) {
      state.loadingServer = normalizedServer;
      promises.push(
        request(`/api/servants?server=${encodeURIComponent(normalizedServer)}`)
          .then((payload) => {
            state.servantsError.delete(normalizedServer);
            state.servantsByServer.set(normalizedServer, Array.isArray(payload.servants) ? payload.servants : []);
          })
          .catch(() => {
            state.servantsError.set(normalizedServer, true);
          })
          .finally(() => {
            if (state.loadingServer === normalizedServer) state.loadingServer = null;
          }),
      );
    }
    if (state.masters === null && !state.mastersLoading && !state.mastersError) {
      state.mastersLoading = true;
      promises.push(
        request("/api/masters")
          .then((payload) => {
            state.mastersError = false;
            state.masters = Array.isArray(payload.masters) ? payload.masters : [];
          })
          .catch(() => {
            state.mastersError = true;
          })
          .finally(() => {
            state.mastersLoading = false;
          }),
      );
    }
    if (state.equips === null && !state.equipsLoading && !state.equipsError) {
      state.equipsLoading = true;
      promises.push(
        request("/api/equip-templates")
          .then((payload) => {
            state.equipsError = false;
            const list = Array.isArray(payload.templates) ? payload.templates : [];
            state.equips = [...new Set(list.filter((item) => item.location === "active" && item.name).map((item) => item.name))];
          })
          .catch(() => {
            state.equipsError = true;
          })
          .finally(() => {
            state.equipsLoading = false;
          }),
      );
    }
    if (promises.length) {
      await Promise.allSettled(promises);
      if (getEditor()?.kind === "settings" && getEditor()?.uiMode === "wizard") {
        render();
      }
    }
  }

  function findServant(servants, name) {
    if (!name) return null;
    return servants.find((s) => s.name === name)
      || servants.find((s) => Array.isArray(s.aliases) && s.aliases.includes(name))
      || null;
  }

  function servantMatchesFilters(servant) {
    if (state.starFilter !== "all") {
      const star = typeof servant.star === "number" ? servant.star : -1;
      if (state.starFilter === "low") {
        if (star < 0 || star > 2) return false;
      } else if (star !== Number(state.starFilter)) {
        return false;
      }
    }
    if (state.classFilter !== "all") {
      if (state.classFilter === "Extra") {
        if (STANDARD_CLASSES.has(servant.class)) return false;
      } else if (servant.class !== state.classFilter) {
        return false;
      }
    }
    if (state.npFilter !== "all" && servant.np_color !== state.npFilter) {
      return false;
    }
    const q = state.searchQuery.trim().toLowerCase();
    if (q) {
      const inName = String(servant.name || "").toLowerCase().includes(q);
      const inClass = String(servant.class || "").toLowerCase().includes(q);
      const inAlias = Array.isArray(servant.aliases)
        && servant.aliases.some((alias) => String(alias || "").toLowerCase().includes(q));
      if (!inName && !inClass && !inAlias) return false;
    }
    return true;
  }

  function syncUsedServant(draft, { includeSlot = null } = {}) {
    const assistIdx = Number.isInteger(draft.assistIdx) ? draft.assistIdx : 2;
    const existing = Array.isArray(draft.usedServant) ? draft.usedServant : [];
    const used = [];
    const addIfValid = (idx) => {
      if (
        Number.isInteger(idx)
        && idx >= 0
        && idx < 6
        && idx !== assistIdx
        && draft[`servant_${idx}_name`]
        && !used.includes(idx)
      ) {
        used.push(idx);
      }
    };
    for (let i = 0; i < 3; i += 1) addIfValid(i);
    for (const idx of existing) {
      if (Number.isInteger(idx) && idx >= 3 && idx < 6) addIfValid(idx);
    }
    if (includeSlot !== null) addIfValid(includeSlot);
    draft.usedServant = used;
  }

  function selectServantForSlot(slotIndex, servantName) {
    const config = readConfig();
    const shouldAutoName = !nameInput.value.trim() || nameInput.value.trim() === state.autoNamedValue;
    writeConfig((draft) => {
      draft[`servant_${slotIndex}_name`] = servantName || null;
      syncUsedServant(draft);
      if (shouldAutoName) {
        const suggested = buildSuggestedName(draft);
        if (suggested) {
          nameInput.value = suggested;
          state.autoNamedValue = suggested;
        }
      }
    }, { rerender: false });

    // Auto-advance to the next empty frontline slot, then reserve slot
    const updated = readConfig();
    if (servantName) {
      let nextEmpty = -1;
      for (let i = 0; i < 6; i += 1) {
        if (!updated[`servant_${i}_name`]) {
          nextEmpty = i;
          break;
        }
      }
      if (nextEmpty !== -1) state.activeSlot = nextEmpty;
    }
    render();
  }

  function renderStepper(container) {
    const steps = [
      { idx: 0, label: t("1. Team & Master") },
      { idx: 1, label: t("2. Assist Setup") },
      { idx: 2, label: t("3. Skills & NPs") },
      { idx: 3, label: t("4. Review & Save") },
    ];
    const bar = document.createElement("div");
    bar.className = "wizard-stepper";
    bar.setAttribute("role", "tablist");
    for (const s of steps) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `wizard-step-tab${state.step === s.idx ? " active" : ""}${state.step > s.idx ? " done" : ""}`;
      btn.textContent = s.label;
      btn.addEventListener("click", () => {
        state.step = s.idx;
        state.pendingTargetSkill = null;
        render();
      });
      bar.append(btn);
    }
    container.append(bar);
  }

  function masterMatchesFilters(master) {
    if (state.masterFilter === "swap") {
      if (!Array.isArray(master.skill_types) || !master.skill_types.includes(2)) return false;
    }
    const q = state.masterSearchQuery.trim().toLowerCase();
    if (!q) return true;
    const parts = [String(master.name || "")];
    if (Array.isArray(master.skills)) parts.push(...master.skills);
    if (Array.isArray(master.skill_details)) {
      for (const d of master.skill_details) {
        if (d?.name) parts.push(d.name);
        if (d?.detail) parts.push(d.detail);
      }
    }
    if (Array.isArray(master.skill_types) && master.skill_types.includes(2)) {
      parts.push("换人 order change swap");
    }
    return parts.join(" ").toLowerCase().includes(q);
  }

  function renderMasterOutfitGrid(gridWrap, countLabel, masters, selectedSn, masterSexVal) {
    if (masters === null) {
      if (state.mastersError) {
        countLabel.textContent = "";
        gridWrap.replaceChildren();
        const err = document.createElement("div");
        err.className = "wizard-empty-hint";
        err.textContent = `${t("Failed to load catalog.")} `;
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "chip-button";
        retryBtn.textContent = t("Retry");
        retryBtn.addEventListener("click", () => {
          state.mastersError = false;
          render();
        });
        err.append(retryBtn);
        gridWrap.append(err);
        return;
      }
      countLabel.textContent = t("Loading...");
      gridWrap.innerHTML = `<div class="wizard-empty-hint">${t("Loading master outfits...")}</div>`;
      return;
    }
    const matched = masters.filter(masterMatchesFilters);
    countLabel.textContent = t("{count} outfits", { count: matched.length });
    const frag = document.createDocumentFragment();

    const showNoneCard = state.masterFilter === "all" && !state.masterSearchQuery.trim();
    if (showNoneCard) {
      const noneCard = document.createElement("button");
      noneCard.type = "button";
      const isNoneSelected = selectedSn === "";
      noneCard.className = `wizard-master-card is-none-card${isNoneSelected ? " active" : ""}`;
      noneCard.dataset.wizardMasterSn = "";
      const noneBox = document.createElement("div");
      noneBox.className = "wizard-master-none-avatar";
      noneBox.textContent = "—";
      const noneInfo = document.createElement("div");
      noneInfo.className = "wizard-master-card-info";
      const noneTitle = document.createElement("div");
      noneTitle.className = "wizard-master-card-name";
      noneTitle.textContent = t("None");
      const noneSub = document.createElement("div");
      noneSub.className = "wizard-master-card-sub";
      noneSub.textContent = t("No outfit check");
      noneInfo.append(noneTitle, noneSub);
      noneCard.append(noneBox, noneInfo);
      noneCard.addEventListener("click", () => {
        writeConfig((draft) => { delete draft.master_equip; });
      });
      frag.append(noneCard);
    }

    for (const m of matched) {
      const snStr = String(m.sn);
      const isSelected = selectedSn === snStr;
      const card = document.createElement("button");
      card.type = "button";
      card.className = `wizard-master-card${isSelected ? " active" : ""}`;
      card.dataset.wizardMasterSn = snStr;

      const skillTooltips = [];
      const skillStrip = document.createElement("div");
      skillStrip.className = "wizard-master-card-skills";
      for (let sk = 0; sk < 3; sk += 1) {
        const display = resolveSkillDisplay(m, sk, `M${sk + 1}`);
        skillTooltips.push(`M${sk + 1} ${display.title}${display.note ? `: ${display.note}` : ""}`);
        if (display.iconKey) {
          const skImg = createAvatarImg(skillIconUrl(display.iconKey), display.title, "wizard-master-sk-icon");
          skImg.title = `${display.title}${display.note ? `\n${display.note}` : ""}`;
          skillStrip.append(skImg);
        }
      }
      if (Array.isArray(m.skill_types) && m.skill_types.includes(2)) {
        const swapPill = document.createElement("span");
        swapPill.className = "wizard-master-swap-badge";
        swapPill.textContent = t("Order Change");
        skillStrip.append(swapPill);
      }

      card.title = `${m.name}\n${skillTooltips.join("\n")}`;
      card.append(createAvatarImg(masterPortraitUrl(m.sn, masterSexVal), m.name, "wizard-master-card-avatar"));

      const infoCol = document.createElement("div");
      infoCol.className = "wizard-master-card-info";
      const nameEl = document.createElement("div");
      nameEl.className = "wizard-master-card-name";
      nameEl.textContent = m.name;
      infoCol.append(nameEl, skillStrip);
      card.append(infoCol);

      card.addEventListener("click", () => {
        writeConfig((draft) => {
          draft.master_equip = m.sn;
        });
      });
      frag.append(card);
    }

    if (!matched.length && !showNoneCard) {
      const empty = document.createElement("div");
      empty.className = "wizard-empty-hint";
      empty.textContent = t("No outfits match the current search.");
      frag.append(empty);
    }
    gridWrap.replaceChildren(frag);
  }

  function renderStep1Team(container, config, servants, server) {
    // Row 1: Server + Selected Master Summary + Gender
    const topMeta = document.createElement("div");
    topMeta.className = "wizard-top-row";

    const serverField = document.createElement("label");
    serverField.className = "field-stack";
    serverField.innerHTML = `<span>${t("Game server")}</span>`;
    const serverSel = document.createElement("select");
    serverSel.className = "field";
    for (const code of ["CH", "CNTW", "JP"]) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = code;
      serverSel.append(opt);
    }
    serverSel.value = server;
    serverSel.addEventListener("change", () => {
      writeConfig((draft) => {
        draft.server = serverSel.value;
        if (serverSel.value === "CNTW" && Array.isArray(draft.skillsLevel)) {
          if (draft.skillsLevel.length > 6) draft.skillsLevel[6] = 0;
          if (draft.skillsLevel.length > 7) draft.skillsLevel[7] = 0;
        }
      });
    });
    serverField.append(serverSel);

    const masterSexVal = config.master_sex === 1 ? 1 : 0;
    const selectedMasterSn = config.master_equip != null ? String(config.master_equip) : "";
    const selectedMasterInfo = (state.masters || []).find((m) => String(m.sn) === selectedMasterSn) || null;

    const masterSummaryField = document.createElement("div");
    masterSummaryField.className = "field-stack wizard-master-field";
    const masterSummaryLabel = document.createElement("span");
    masterSummaryLabel.textContent = t("Master outfit");
    const masterSummaryBar = document.createElement("div");
    masterSummaryBar.className = "wizard-master-summary-bar";
    if (selectedMasterSn !== "") {
      masterSummaryBar.append(
        createAvatarImg(masterPortraitUrl(selectedMasterSn, masterSexVal), selectedMasterInfo?.name || "", "wizard-master-thumb"),
      );
      const summaryText = document.createElement("div");
      summaryText.className = "wizard-master-summary-text";
      const summaryName = document.createElement("strong");
      summaryName.textContent = selectedMasterInfo?.name || `#${selectedMasterSn}`;
      summaryText.append(summaryName);
      if (selectedMasterInfo) {
        const skNames = [0, 1, 2]
          .map((idx) => resolveSkillDisplay(selectedMasterInfo, idx, "").title)
          .filter(Boolean)
          .join(" · ");
        if (skNames) {
          const sub = document.createElement("small");
          sub.textContent = skNames;
          summaryText.append(sub);
        }
      }
      const clearMasterBtn = document.createElement("button");
      clearMasterBtn.type = "button";
      clearMasterBtn.className = "chip-button wizard-slot-clear";
      clearMasterBtn.textContent = "×";
      clearMasterBtn.title = t("Clear");
      clearMasterBtn.addEventListener("click", () => {
        writeConfig((draft) => { delete draft.master_equip; });
      });
      masterSummaryBar.append(summaryText, clearMasterBtn);
    } else {
      const emptyHint = document.createElement("span");
      emptyHint.className = "wizard-master-summary-empty";
      emptyHint.textContent = t("None — click a Master outfit card below to select");
      masterSummaryBar.append(emptyHint);
    }
    masterSummaryField.append(masterSummaryLabel, masterSummaryBar);

    const sexField = document.createElement("label");
    sexField.className = "field-stack";
    sexField.innerHTML = `<span>${t("Master gender")}</span>`;
    const sexSel = document.createElement("select");
    sexSel.className = "field";
    for (const [val, lbl] of [["0", t("Female")], ["1", t("Male")]]) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = lbl;
      sexSel.append(opt);
    }
    sexSel.value = String(masterSexVal);
    sexSel.addEventListener("change", () => {
      writeConfig((draft) => { draft.master_sex = Number(sexSel.value); });
    });
    sexField.append(sexSel);

    topMeta.append(serverField, masterSummaryField, sexField);
    container.append(topMeta);

    // Visual Master Outfit Card Grid
    const masterPickerBox = document.createElement("div");
    masterPickerBox.className = "wizard-picker-box wizard-master-box";
    const masterPickerTop = document.createElement("div");
    masterPickerTop.className = "wizard-picker-search-row";
    const masterPickLabel = document.createElement("span");
    masterPickLabel.className = "wizard-picking-label";
    masterPickLabel.textContent = t("Pick Master Outfit");

    const masterFilterRow = document.createElement("div");
    masterFilterRow.className = "wizard-filter-row";
    for (const [fVal, fLbl] of [["all", t("All")], ["swap", t("Order Change")]]) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `chip-button${state.masterFilter === fVal ? " active" : ""}`;
      chip.textContent = fLbl;
      chip.addEventListener("click", () => {
        state.masterFilter = fVal;
        render();
      });
      masterFilterRow.append(chip);
    }

    const masterSearchInput = document.createElement("input");
    masterSearchInput.type = "search";
    masterSearchInput.className = "field";
    masterSearchInput.placeholder = t("Search master outfits or skills (e.g. Order Change, NP)...");
    masterSearchInput.value = state.masterSearchQuery;
    const masterCountLabel = document.createElement("span");
    masterCountLabel.className = "wizard-picker-count";
    masterSearchInput.addEventListener("input", () => {
      state.masterSearchQuery = masterSearchInput.value;
      renderMasterOutfitGrid(masterGridWrap, masterCountLabel, state.masters, selectedMasterSn, masterSexVal);
    });
    masterPickerTop.append(masterPickLabel, masterFilterRow, masterSearchInput, masterCountLabel);

    const masterGridWrap = document.createElement("div");
    masterGridWrap.className = "wizard-master-grid";
    renderMasterOutfitGrid(masterGridWrap, masterCountLabel, state.masters, selectedMasterSn, masterSexVal);
    masterPickerBox.append(masterPickerTop, masterGridWrap);
    container.append(masterPickerBox);

    // Row 2: 6 Team Slots
    const slotsHeading = document.createElement("div");
    slotsHeading.className = "wizard-section-head";
    slotsHeading.innerHTML = `<strong>${t("Party Formation (click a slot, then pick a Servant below)")}</strong>`;
    container.append(slotsHeading);

    const slotsGrid = document.createElement("div");
    slotsGrid.className = "wizard-slots-grid";
    const assistIdx = Number.isInteger(config.assistIdx) ? config.assistIdx : 2;
    for (let i = 0; i < 6; i += 1) {
      const name = typeof config[`servant_${i}_name`] === "string" ? config[`servant_${i}_name`] : "";
      const info = findServant(servants, name);
      const card = document.createElement("div");
      card.className = `wizard-slot-card${state.activeSlot === i ? " active" : ""}${assistIdx === i ? " is-assist" : ""}${i >= 3 ? " is-reserve" : ""}`;
      card.addEventListener("click", () => {
        state.activeSlot = i;
        render();
      });

      const badgeRow = document.createElement("div");
      badgeRow.className = "wizard-slot-badges";
      const posBadge = document.createElement("span");
      posBadge.className = "wizard-pos-tag";
      posBadge.textContent = `${i + 1}${i < 3 ? "" : t(" (Sub)")}`;
      badgeRow.append(posBadge);
      if (assistIdx === i) {
        const aBadge = document.createElement("span");
        aBadge.className = "wizard-assist-tag";
        aBadge.textContent = t("Support");
        badgeRow.append(aBadge);
      }

      const body = document.createElement("div");
      body.className = "wizard-slot-body";
      if (name) {
        body.append(createAvatarImg(servantPortraitUrl(info?.name || name, server, info?.face_index), name, "wizard-slot-avatar"));
        const nameEl = document.createElement("div");
        nameEl.className = "wizard-slot-name";
        nameEl.textContent = name;
        nameEl.title = name;
        body.append(nameEl);
      } else {
        const empty = document.createElement("div");
        empty.className = "wizard-slot-empty";
        empty.textContent = t("+ Pick Servant");
        body.append(empty);
      }

      const actions = document.createElement("div");
      actions.className = "wizard-slot-actions";
      const setAssistBtn = document.createElement("button");
      setAssistBtn.type = "button";
      setAssistBtn.className = `chip-button${assistIdx === i ? " active" : ""}`;
      setAssistBtn.textContent = t("Support");
      setAssistBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        writeConfig((draft) => {
          draft.assistIdx = i;
          syncUsedServant(draft);
        });
      });
      actions.append(setAssistBtn);
      if (name) {
        const clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.className = "chip-button wizard-slot-clear";
        clearBtn.textContent = "×";
        clearBtn.title = t("Clear");
        clearBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          selectServantForSlot(i, "");
        });
        actions.append(clearBtn);
      }

      card.append(badgeRow, body, actions);
      slotsGrid.append(card);
    }
    container.append(slotsGrid);

    // Row 3: Visual Servant Picker
    const pickerBox = document.createElement("div");
    pickerBox.className = "wizard-picker-box";

    const pickerTop = document.createElement("div");
    pickerTop.className = "wizard-picker-search-row";
    const slotHint = document.createElement("span");
    slotHint.className = "wizard-picking-label";
    slotHint.textContent = t("Picking for Slot {slot}", { slot: state.activeSlot + 1 });
    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "field";
    searchInput.placeholder = t("Search name or nickname (e.g. 光狐, 术呆, 摩根)...");
    searchInput.value = state.searchQuery;
    searchInput.addEventListener("input", () => {
      state.searchQuery = searchInput.value;
      renderServantGrid(gridWrap, countLabel, servants, server);
    });
    const countLabel = document.createElement("span");
    countLabel.className = "wizard-picker-count";
    pickerTop.append(slotHint, searchInput, countLabel);
    pickerBox.append(pickerTop);

    // Popular quick-pick chips
    const popularAvailable = POPULAR_SUPPORT_NAMES
      .map((n) => findServant(servants, n))
      .filter(Boolean);
    if (popularAvailable.length) {
      const popRow = document.createElement("div");
      popRow.className = "wizard-filter-row";
      const popLbl = document.createElement("span");
      popLbl.className = "wizard-filter-label";
      popLbl.textContent = t("Frequent");
      popRow.append(popLbl);
      for (const s of popularAvailable) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip-button";
        chip.textContent = s.name;
        chip.addEventListener("click", () => selectServantForSlot(state.activeSlot, s.name));
        popRow.append(chip);
      }
      pickerBox.append(popRow);
    }

    // Star + NP filter row
    const starRow = document.createElement("div");
    starRow.className = "wizard-filter-row";
    const starLbl = document.createElement("span");
    starLbl.className = "wizard-filter-label";
    starLbl.textContent = t("Rarity");
    starRow.append(starLbl);
    for (const [val, txt] of [["all", t("All")], ["5", "5★"], ["4", "4★"], ["3", "3★"], ["low", "≤2★"]]) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `chip-button${state.starFilter === val ? " active" : ""}`;
      chip.textContent = txt;
      chip.addEventListener("click", () => {
        state.starFilter = val;
        render();
      });
      starRow.append(chip);
    }
    const npSep = document.createElement("span");
    npSep.className = "wizard-filter-label wizard-filter-sep";
    npSep.textContent = t("NP");
    starRow.append(npSep);
    for (const [val, txt, cls] of [["all", t("All"), ""], ["B", t("Buster"), "np-b"], ["A", t("Arts"), "np-a"], ["Q", t("Quick"), "np-q"]]) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `chip-button ${cls}${state.npFilter === val ? " active" : ""}`;
      chip.textContent = txt;
      chip.addEventListener("click", () => {
        state.npFilter = val;
        render();
      });
      starRow.append(chip);
    }
    pickerBox.append(starRow);

    // Class filter row
    const classRow = document.createElement("div");
    classRow.className = "wizard-filter-row";
    const classLbl = document.createElement("span");
    classLbl.className = "wizard-filter-label";
    classLbl.textContent = t("Class");
    classRow.append(classLbl);
    for (const item of CLASS_GROUPS) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `chip-button${state.classFilter === item.key ? " active" : ""}`;
      chip.textContent = t(item.labelKey);
      chip.addEventListener("click", () => {
        state.classFilter = item.key;
        render();
      });
      classRow.append(chip);
    }
    pickerBox.append(classRow);

    const gridWrap = document.createElement("div");
    gridWrap.className = "wizard-servant-grid";
    renderServantGrid(gridWrap, countLabel, servants, server);
    pickerBox.append(gridWrap);
    container.append(pickerBox);
  }

  function renderServantGrid(gridWrap, countLabel, servants, server) {
    if (!state.servantsByServer.has(server)) {
      if (state.servantsError.get(server)) {
        countLabel.textContent = "";
        gridWrap.replaceChildren();
        const err = document.createElement("div");
        err.className = "wizard-empty-hint";
        err.textContent = `${t("Failed to load catalog.")} `;
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "chip-button";
        retryBtn.textContent = t("Retry");
        retryBtn.addEventListener("click", () => {
          state.servantsError.delete(server);
          render();
        });
        err.append(retryBtn);
        gridWrap.append(err);
        return;
      }
      countLabel.textContent = t("Loading...");
      gridWrap.innerHTML = `<div class="wizard-empty-hint">${t("Loading servant catalog...")}</div>`;
      return;
    }
    const matched = servants.filter(servantMatchesFilters);
    matched.sort((a, b) => (b.star ?? -1) - (a.star ?? -1) || a.name.localeCompare(b.name, "zh-CN"));
    countLabel.textContent = t("{count} servants", { count: matched.length });
    const shown = matched.slice(0, 120);
    const frag = document.createDocumentFragment();
    for (const servant of shown) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "wizard-servant-card";
      card.title = `${servant.name}${servant.aliases?.length ? ` (${servant.aliases.join(" / ")})` : ""}`;
      card.append(createAvatarImg(servantPortraitUrl(servant.name, server, servant.face_index), servant.name, "wizard-card-avatar"));
      const meta = document.createElement("div");
      meta.className = "wizard-card-meta";
      if (typeof servant.star === "number") {
        const star = document.createElement("span");
        star.className = `wizard-star-pill star-${servant.star}`;
        star.textContent = `${servant.star}★`;
        meta.append(star);
      }
      if (servant.np_color) {
        const np = document.createElement("span");
        np.className = `wizard-np-dot np-${servant.np_color.toLowerCase()}`;
        np.textContent = servant.np_color;
        meta.append(np);
      }
      const name = document.createElement("div");
      name.className = "wizard-card-name";
      name.textContent = servant.name;
      card.append(meta, name);
      card.addEventListener("click", () => selectServantForSlot(state.activeSlot, servant.name));
      frag.append(card);
    }
    if (matched.length > shown.length) {
      const more = document.createElement("div");
      more.className = "wizard-empty-hint";
      more.textContent = t("Showing first {shown} of {total} — narrow with filters or search.", { shown: shown.length, total: matched.length });
      frag.append(more);
    }
    if (!shown.length) {
      const empty = document.createElement("div");
      empty.className = "wizard-empty-hint";
      empty.textContent = t("No servants match the current filters.");
      frag.append(empty);
    }
    gridWrap.replaceChildren(frag);
  }

  function renderStep2Assist(container, config, servants, server) {
    const assistIdx = Number.isInteger(config.assistIdx) ? config.assistIdx : 2;
    const assistName = config[`servant_${assistIdx}_name`] || "";
    const assistServant = findServant(servants, assistName);
    const mode = config.assistMode || "从者礼装";
    const isGrand = GRAND_MODES.has(mode);
    const usesServant = !["不识别", "仅礼装", "冠位助战仅礼装"].includes(mode);
    const usesEquip = !["不识别", "仅从者"].includes(mode);

    // Target summary banner
    const banner = document.createElement("div");
    banner.className = "wizard-assist-banner";
    if (assistName) {
      banner.append(createAvatarImg(servantPortraitUrl(assistServant?.name || assistName, server, assistServant?.face_index), assistName, "wizard-slot-avatar"));
      const txt = document.createElement("div");
      txt.innerHTML = `<strong>${t("Target Support (Slot {slot})", { slot: assistIdx + 1 })}</strong><div>${assistName}</div>`;
      banner.append(txt);
    } else {
      const txt = document.createElement("div");
      txt.textContent = t("No support servant assigned to Slot {slot} yet — you can pick one in Step 1 or use CE-only mode.", { slot: assistIdx + 1 });
      banner.append(txt);
    }
    container.append(banner);

    // Assist mode cards
    const modeRow = document.createElement("div");
    modeRow.className = "wizard-mode-cards";
    for (const [val, labelKey] of [
      ["从者礼装", "Servant + CE"],
      ["冠位助战", "Grand + CE"],
      ["冠位助战仅礼装", "Grand CE only"],
      ["仅从者", "Servant only"],
      ["仅礼装", "CE only"],
      ["不识别", "First support"],
    ]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `wizard-mode-card${mode === val ? " active" : ""}`;
      btn.textContent = t(labelKey);
      btn.addEventListener("click", () => {
        writeConfig((draft) => {
          const wasGrand = GRAND_MODES.has(draft.assistMode);
          draft.assistMode = val;
          if (GRAND_MODES.has(val)) {
            const slots = normalizeAssistEquipArray(draft.assistEquip, true, wasGrand);
            draft.assistEquip = slots.map((slot) => (slot.length ? slot : null));
            draft.jbType = draft.jbType || "任意";
          } else if (val === "仅从者" || val === "不识别") {
            draft.assistEquip = [];
          } else {
            draft.assistEquip = normalizeAssistEquipArray(draft.assistEquip, false, wasGrand);
          }
        });
      });
      modeRow.append(btn);
    }
    container.append(modeRow);

    if (usesServant || usesEquip || isGrand) {
      const reqCard = document.createElement("div");
      reqCard.className = "wizard-card-block";
      if (usesServant) {
        const skills = Array.isArray(config.skillsLevel) ? [...config.skillsLevel] : [10, 10, 10, 0, 0, 0, 0, 0];
        while (skills.length < 8) skills.push(0);

        // Skill quick presets
        const skillPresetRow = document.createElement("div");
        skillPresetRow.className = "wizard-filter-row";
        const spLbl = document.createElement("span");
        spLbl.className = "wizard-filter-label";
        spLbl.textContent = t("Skill preset");
        skillPresetRow.append(spLbl);
        for (const [lbl, preset] of [
          [t("Any"), [0, 0, 0, 0, 0, 0, 0, 0]],
          ["310", [10, 10, 10, 0, 0, 0, 0, 0]],
          [t("310 + Append 2 Lv.10"), [10, 10, 10, 0, 10, 0, 0, 0]],
        ]) {
          const isCurrent = preset.every((v, idx) => Number(skills[idx] || 0) === v);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = `chip-button${isCurrent ? " active" : ""}`;
          btn.textContent = lbl;
          btn.addEventListener("click", () => {
            writeConfig((draft) => { draft.skillsLevel = [...preset]; });
          });
          skillPresetRow.append(btn);
        }
        reqCard.append(skillPresetRow);

        // NP level + Servant level quick chips
        const npRow = document.createElement("div");
        npRow.className = "wizard-filter-row";
        const npLbl = document.createElement("span");
        npLbl.className = "wizard-filter-label";
        npLbl.textContent = t("Min NP");
        npRow.append(npLbl);
        for (const lv of [1, 2, 3, 4, 5]) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = `chip-button${Number(config.NPlevel || 1) === lv ? " active" : ""}`;
          btn.textContent = lv === 1 ? t("Any") : `${lv}`;
          btn.addEventListener("click", () => {
            writeConfig((draft) => { draft.NPlevel = lv; });
          });
          npRow.append(btn);
        }
        const lvLbl = document.createElement("span");
        lvLbl.className = "wizard-filter-label wizard-filter-sep";
        lvLbl.textContent = t("Min Lv.");
        npRow.append(lvLbl);
        for (const lv of [1, 90, 100, 120]) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = `chip-button${Number(config.servantLevel || 1) === lv ? " active" : ""}`;
          btn.textContent = lv === 1 ? t("Any") : String(lv);
          btn.addEventListener("click", () => {
            writeConfig((draft) => { draft.servantLevel = lv; });
          });
          npRow.append(btn);
        }
        reqCard.append(npRow);
      }

      // Toggles
      const toggleRow = document.createElement("div");
      toggleRow.className = "wizard-toggle-strip";
      for (const [key, labelKey] of [
        ...(usesServant ? [["onlyFriendAssist", "Friends only"]] : []),
        ...(usesEquip ? [["fullEquip", "Max limit break CE"]] : []),
        ...(isGrand ? [["noGrandRefresh", "Refresh at grand boundary"]] : []),
      ]) {
        const lbl = document.createElement("label");
        lbl.className = "checkline";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = Boolean(config[key]);
        cb.addEventListener("change", () => {
          writeConfig((draft) => { draft[key] = cb.checked ? 1 : 0; });
        });
        const sp = document.createElement("span");
        sp.textContent = t(labelKey);
        lbl.append(cb, sp);
        toggleRow.append(lbl);
      }
      if (isGrand) {
        const bondLbl = document.createElement("label");
        bondLbl.className = "wizard-inline-select";
        bondLbl.innerHTML = `<span>${t("Grand bond CE")}</span>`;
        const bondSel = document.createElement("select");
        bondSel.className = "field";
        for (const [val, lk] of [["任意", "Any"], ["初始", "Original"], ["NP50", "NP 50%"]]) {
          const opt = document.createElement("option");
          opt.value = val;
          opt.textContent = t(lk);
          bondSel.append(opt);
        }
        bondSel.value = config.jbType || "任意";
        bondSel.addEventListener("change", () => {
          writeConfig((draft) => { draft.jbType = bondSel.value; });
        });
        bondLbl.append(bondSel);
        toggleRow.append(bondLbl);
      }
      reqCard.append(toggleRow);
      container.append(reqCard);
    }

    if (usesEquip) {
      const ceCard = document.createElement("div");
      ceCard.className = "wizard-card-block";
      const header = document.createElement("div");
      header.className = "wizard-picker-search-row";
      const title = document.createElement("strong");
      title.textContent = t("Assist CEs");
      const ceSearch = document.createElement("input");
      ceSearch.type = "search";
      ceSearch.className = "field";
      ceSearch.placeholder = t("Filter CEs...");
      ceSearch.value = state.ceSearchQuery;
      header.append(title, ceSearch);
      ceCard.append(header);

      const normalized = normalizeAssistEquipArray(config.assistEquip, isGrand);
      if (isGrand) {
        const slotTabs = document.createElement("div");
        slotTabs.className = "wizard-filter-row";
        for (const [idx, lk] of [[0, "Normal CE"], [1, "Bond CE"], [2, "Reward CE"]]) {
          const count = normalized[idx].length;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = `chip-button${state.grandCeSlot === idx ? " active" : ""}`;
          btn.textContent = `${t(lk)} (${count})`;
          btn.addEventListener("click", () => {
            state.grandCeSlot = idx;
            render();
          });
          slotTabs.append(btn);
        }
        ceCard.append(slotTabs);
      }

      const selectedList = isGrand ? normalized[state.grandCeSlot] : normalized;
      const ceGrid = document.createElement("div");
      ceGrid.className = "wizard-ce-grid";

      const renderCeItems = () => {
        const q = state.ceSearchQuery.trim().toLowerCase();
        const catalog = state.equips || [];
        const allNames = [...new Set([...selectedList, ...catalog])];
        const filtered = q ? allNames.filter((n) => n.toLowerCase().includes(q)) : allNames;
        const frag = document.createDocumentFragment();
        for (const name of filtered) {
          const selected = selectedList.includes(name);
          const item = document.createElement("button");
          item.type = "button";
          item.className = `wizard-ce-card${selected ? " active" : ""}`;
          if (catalog.includes(name)) {
            item.append(createAvatarImg(`/api/equip-templates/${encodeURIComponent(name)}/image?location=active`, name, "wizard-ce-thumb"));
          }
          const lbl = document.createElement("span");
          lbl.textContent = name;
          item.append(lbl);
          item.addEventListener("click", () => {
            writeConfig((draft) => {
              const next = normalizeAssistEquipArray(draft.assistEquip, isGrand);
              const target = isGrand ? next[state.grandCeSlot] : next;
              const idx = target.indexOf(name);
              if (idx >= 0) target.splice(idx, 1);
              else target.push(name);
              if (isGrand) {
                draft.assistEquip = next.map((slot) => (slot.length ? slot : null));
              } else {
                draft.assistEquip = next;
              }
            });
          });
          frag.append(item);
        }
        if (!filtered.length) {
          const empty = document.createElement("div");
          empty.className = "wizard-empty-hint";
          empty.textContent = t("No CE templates matched.");
          frag.append(empty);
        }
        ceGrid.replaceChildren(frag);
      };

      ceSearch.addEventListener("input", () => {
        state.ceSearchQuery = ceSearch.value;
        renderCeItems();
      });
      renderCeItems();
      ceCard.append(ceGrid);
      container.append(ceCard);
    }
  }

  function renderStep3Timeline(container, config, servants, server) {
    const waveCount = extractWaveCount(config);
    if (state.activeWave > waveCount) state.activeWave = waveCount;
    const wave = state.activeWave;
    const skillKey = `round${wave}_turn0_skill`;
    const npKey = `round${wave}_turn0_np`;
    const stratKey = `round${wave}_turn0_strategy`;
    const skillList = Array.isArray(config[skillKey]) ? config[skillKey] : [];
    const npList = Array.isArray(config[npKey]) ? config[npKey] : [];

    // Wave tabs bar
    const waveBar = document.createElement("div");
    waveBar.className = "wizard-wave-bar";
    for (let w = 1; w <= waveCount; w += 1) {
      const wSkills = Array.isArray(config[`round${w}_turn0_skill`]) ? config[`round${w}_turn0_skill`].length : 0;
      const wNps = Array.isArray(config[`round${w}_turn0_np`]) ? config[`round${w}_turn0_np`].length : 0;
      const tab = document.createElement("div");
      tab.className = `wizard-wave-tab${wave === w ? " active" : ""}`;
      tab.dataset.wave = String(w);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wizard-wave-select";
      btn.textContent = `${t("Wave {round}", { round: w })} (${wSkills}S/${wNps}NP)`;
      btn.addEventListener("click", () => {
        state.activeWave = w;
        state.pendingTargetSkill = null;
        render();
      });
      tab.append(btn);

      if (waveCount > 1) {
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "wizard-wave-del";
        delBtn.textContent = "×";
        const delLabel = t("Delete wave {round}", { round: w });
        delBtn.title = delLabel;
        delBtn.setAttribute("aria-label", delLabel);
        delBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          if (hasWaveData(config, w)) {
            const ok = window.confirm(t("Delete wave {round} and all its fields?", { round: w }));
            if (!ok) return;
          }
          const nextCount = Math.max(1, waveCount - 1);
          if (w < state.activeWave) {
            state.activeWave -= 1;
          } else if (state.activeWave > nextCount) {
            state.activeWave = nextCount;
          }
          state.pendingTargetSkill = null;
          writeConfig((draft) => {
            removeWaveFromConfig(draft, w);
          });
        });
        tab.append(delBtn);
      }

      waveBar.append(tab);
    }
    const addWaveBtn = document.createElement("button");
    addWaveBtn.type = "button";
    addWaveBtn.className = "chip-button";
    addWaveBtn.textContent = `+ ${t("Add Wave")}`;
    addWaveBtn.addEventListener("click", () => {
      const nextWave = waveCount + 1;
      state.activeWave = nextWave;
      state.pendingTargetSkill = null;
      writeConfig((draft) => {
        draft[`round${nextWave}_turns`] = 1;
        draft[`round${nextWave}_turn0_skill`] = [];
        draft[`round${nextWave}_turn0_np`] = [];
      });
    });
    waveBar.append(addWaveBtn);
    container.append(waveBar);

    const hasExtraWaveTurns = Number(config[`round${wave}_turns`] || 1) > 1
      || (Array.isArray(config[`round${wave}_extraSkill`]) && config[`round${wave}_extraSkill`].length > 0)
      || (Array.isArray(config[`round${wave}_extraStrategy`]) && config[`round${wave}_extraStrategy`].length > 0);
    if (hasExtraWaveTurns) {
      const note = document.createElement("div");
      note.className = "wizard-empty-hint";
      note.textContent = t("This wave has additional turns or extra-turn actions — edit them in Pro Mode.");
      container.append(note);
    }

    const pushSkillCommand = (command, { includeUsedSlot = null } = {}) => {
      state.pendingTargetSkill = null;
      writeConfig((draft) => {
        draft[`round${wave}_turns`] = Math.max(1, Number(draft[`round${wave}_turns`] || 0));
        const arr = Array.isArray(draft[skillKey]) ? [...draft[skillKey]] : [];
        arr.push(command);
        draft[skillKey] = arr;
        if (includeUsedSlot !== null) {
          syncUsedServant(draft, { includeSlot: includeUsedSlot });
        }
      });
    };

    // Compute current battlefield lineup after any Order Change swaps or replacements up to this point
    const waveStartLineup = computeLineupBefore(config, wave, 0);
    const activeLineup = computeLineupBefore(config, wave, skillList.length);
    const lineupServantName = (lineup, posIndex) => {
      const origSlot = lineup[posIndex];
      if (origSlot == null) return "";
      const raw = config[`servant_${origSlot}_name`];
      return typeof raw === "string" ? raw : "";
    };

    // Visual Frontline + Master Skill Bar
    const board = document.createElement("div");
    board.className = "wizard-battle-board";

    for (let slot = 0; slot < 3; slot += 1) {
      const sName = lineupServantName(activeLineup, slot);
      const info = findServant(servants, sName);
      const canonicalName = info?.name || sName;
      const col = document.createElement("div");
      col.className = "wizard-servant-skill-col";

      const head = document.createElement("div");
      head.className = "wizard-skill-col-head";
      if (sName) {
        head.append(createAvatarImg(servantPortraitUrl(canonicalName, server, info?.face_index), sName, "wizard-mini-avatar"));
      }
      const title = document.createElement("span");
      title.textContent = sName ? `${slot + 1}·${sName}` : t("Servant {slot}", { slot: slot + 1 });
      head.append(title);
      col.append(head);

      const btns = document.createElement("div");
      btns.className = "wizard-skill-buttons";
      for (let sk = 0; sk < 3; sk += 1) {
        const skillNum = slot * 3 + sk + 1;
        const display = resolveSkillDisplay(info, sk, t("Skill {index}", { index: sk + 1 }));
        const skType = info?.skill_types?.[sk];
        const specialSpec = resolveWizardSpecialSkill(canonicalName, slot, sk, server);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "wizard-skill-btn";
        if (display.iconKey) {
          btn.append(createAvatarImg(skillIconUrl(display.iconKey), display.iconKey, "wizard-skill-icon"));
        }
        const textWrap = document.createElement("div");
        textWrap.className = "wizard-skill-text";
        const topLine = document.createElement("div");
        topLine.className = "wizard-skill-top";
        const idxEl = document.createElement("span");
        idxEl.className = "sk-idx";
        idxEl.textContent = `S${sk + 1}`;
        const nameEl = document.createElement("span");
        nameEl.className = "sk-name";
        nameEl.textContent = display.title;
        topLine.append(idxEl, nameEl);
        textWrap.append(topLine);
        if (display.note) {
          const noteEl = document.createElement("div");
          noteEl.className = "sk-note";
          noteEl.textContent = display.note;
          textWrap.append(noteEl);
        }
        btn.append(textWrap);
        btn.title = `${title.textContent} · S${sk + 1} ${display.title}${display.note ? `\n${display.note}` : ""}`;
        btn.addEventListener("click", () => {
          if (specialSpec) {
            state.pendingTargetSkill = {
              skillNum,
              mode: "special",
              spec: specialSpec,
              selectedOption: specialSpec.options[0]?.value,
              label: `${title.textContent} · ${display.title}`,
            };
            render();
          } else if (skType === 1) {
            state.pendingTargetSkill = { skillNum, isSwap: false, label: `${title.textContent} · ${display.title}` };
            render();
          } else {
            pushSkillCommand(skillNum);
          }
        });
        btns.append(btn);
      }
      col.append(btns);
      board.append(col);
    }

    // Master Outfit Skill Column
    const masterInfo = (state.masters || []).find((m) => String(m.sn) === String(config.master_equip));
    const mCol = document.createElement("div");
    mCol.className = "wizard-servant-skill-col wizard-master-col";
    const mHead = document.createElement("div");
    mHead.className = "wizard-skill-col-head";
    if (masterInfo) {
      mHead.append(createAvatarImg(masterPortraitUrl(masterInfo.sn, config.master_sex === 1 ? 1 : 0), masterInfo.name, "wizard-mini-avatar"));
    }
    const mTitle = document.createElement("span");
    mTitle.textContent = masterInfo ? masterInfo.name : t("Master");
    mHead.append(mTitle);
    mCol.append(mHead);
    const mBtns = document.createElement("div");
    mBtns.className = "wizard-skill-buttons";
    for (let sk = 0; sk < 3; sk += 1) {
      const skillNum = 10 + sk;
      const display = resolveSkillDisplay(masterInfo, sk, t("Skill {index}", { index: sk + 1 }));
      const skType = masterInfo?.skill_types?.[sk];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wizard-skill-btn";
      if (display.iconKey) {
        btn.append(createAvatarImg(skillIconUrl(display.iconKey), display.iconKey, "wizard-skill-icon"));
      }
      const textWrap = document.createElement("div");
      textWrap.className = "wizard-skill-text";
      const topLine = document.createElement("div");
      topLine.className = "wizard-skill-top";
      const idxEl = document.createElement("span");
      idxEl.className = "sk-idx";
      idxEl.textContent = `M${sk + 1}`;
      const nameEl = document.createElement("span");
      nameEl.className = "sk-name";
      nameEl.textContent = display.title;
      topLine.append(idxEl, nameEl);
      textWrap.append(topLine);
      if (display.note) {
        const noteEl = document.createElement("div");
        noteEl.className = "sk-note";
        noteEl.textContent = display.note;
        textWrap.append(noteEl);
      }
      btn.append(textWrap);
      btn.title = `${mTitle.textContent} · M${sk + 1} ${display.title}${display.note ? `\n${display.note}` : ""}`;
      btn.addEventListener("click", () => {
        if (skType === 2) {
          state.pendingTargetSkill = { skillNum, isSwap: true, front: 1, reserve: 4, label: `${display.title} (M${sk + 1})` };
          render();
        } else if (skType === 1 || skType === 3) {
          state.pendingTargetSkill = { skillNum, isSwap: false, label: `${mTitle.textContent} · ${display.title}` };
          render();
        } else {
          pushSkillCommand(skillNum);
        }
      });
      mBtns.append(btn);
    }
    mCol.append(mBtns);
    board.append(mCol);
    container.append(board);

    // Inline Target / Order Change / Special Skill Option Popover Bar
    if (state.pendingTargetSkill) {
      const pending = state.pendingTargetSkill;
      const bar = document.createElement("div");
      bar.className = "wizard-target-bar";
      const prompt = document.createElement("strong");
      if (pending.mode === "special") {
        prompt.textContent = t("Select option for {skill}:", { skill: pending.label });
      } else {
        prompt.textContent = pending.isSwap ? `${pending.label}:` : t("Target for {skill}:", { skill: pending.label });
      }
      bar.append(prompt);

      if (pending.mode === "special" && pending.spec) {
        const spec = pending.spec;
        if (spec.kind === "kukulkan" && spec.needsTarget) {
          const optSel = document.createElement("select");
          optSel.className = "field";
          for (const optDef of spec.options) {
            const opt = document.createElement("option");
            opt.value = String(optDef.value);
            opt.textContent = t(optDef.labelKey);
            optSel.append(opt);
          }
          optSel.value = String(pending.selectedOption ?? 1);
          optSel.addEventListener("change", () => {
            pending.selectedOption = Number(optSel.value);
          });
          bar.append(optSel);
          for (let s = 1; s <= 3; s += 1) {
            const nm = lineupServantName(activeLineup, s - 1);
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "primary-button";
            btn.textContent = nm ? `${s}·${nm}` : t("Servant {slot}", { slot: s });
            btn.addEventListener("click", () => {
              pushSkillCommand(buildWizardSpecialCommand(spec, Number(optSel.value), s));
            });
            bar.append(btn);
          }
        } else if (spec.kind === "hakuno-needs") {
          const castOnceBtn = document.createElement("button");
          castOnceBtn.type = "button";
          castOnceBtn.className = "primary-button";
          castOnceBtn.textContent = t("Cast Once");
          castOnceBtn.addEventListener("click", () => {
            pushSkillCommand(buildWizardSpecialCommand(spec, []));
          });
          const hint = document.createElement("span");
          hint.className = "wizard-picker-count";
          hint.textContent = t("Custom card-reroll combinations can be edited in Pro Mode.");
          bar.append(castOnceBtn, hint);
        } else {
          for (const optDef of spec.options) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "primary-button";
            btn.textContent = t(optDef.labelKey);
            btn.addEventListener("click", () => {
              pushSkillCommand(buildWizardSpecialCommand(spec, optDef.value));
            });
            bar.append(btn);
          }
        }
      } else if (pending.isSwap) {
        const frontSel = document.createElement("select");
        frontSel.className = "field";
        for (let s = 1; s <= 3; s += 1) {
          const opt = document.createElement("option");
          opt.value = String(s);
          const nm = lineupServantName(activeLineup, s - 1);
          opt.textContent = nm ? `${s}·${nm}` : t("Servant {slot}", { slot: s });
          frontSel.append(opt);
        }
        frontSel.value = String(pending.front || 1);
        const arrow = document.createElement("span");
        arrow.textContent = "↔";
        const resSel = document.createElement("select");
        resSel.className = "field";
        for (let s = 4; s <= 6; s += 1) {
          const opt = document.createElement("option");
          opt.value = String(s);
          const nm = lineupServantName(activeLineup, s - 1);
          opt.textContent = nm ? `${s}·${nm}` : t("Servant {slot}", { slot: s });
          resSel.append(opt);
        }
        resSel.value = String(pending.reserve || 4);
        const okBtn = document.createElement("button");
        okBtn.type = "button";
        okBtn.className = "primary-button";
        okBtn.textContent = t("Add");
        okBtn.addEventListener("click", () => {
          const frontPos = Number(frontSel.value);
          const reservePos = Number(resSel.value);
          const reserveOrigSlot = activeLineup[reservePos - 1];
          pushSkillCommand([pending.skillNum, frontPos, reservePos], {
            includeUsedSlot: Number.isInteger(reserveOrigSlot) ? reserveOrigSlot : null,
          });
        });
        bar.append(frontSel, arrow, resSel, okBtn);
      } else {
        for (let s = 1; s <= 3; s += 1) {
          const nm = lineupServantName(activeLineup, s - 1);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "primary-button";
          btn.textContent = nm ? `${s}·${nm}` : t("Servant {slot}", { slot: s });
          btn.addEventListener("click", () => pushSkillCommand([pending.skillNum, s]));
          bar.append(btn);
        }
        const noTargetBtn = document.createElement("button");
        noTargetBtn.type = "button";
        noTargetBtn.className = "ghost-button";
        noTargetBtn.textContent = t("No target");
        noTargetBtn.addEventListener("click", () => pushSkillCommand(pending.skillNum));
        bar.append(noTargetBtn);
      }
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "ghost-button";
      cancelBtn.textContent = t("Cancel");
      cancelBtn.addEventListener("click", () => {
        state.pendingTargetSkill = null;
        render();
      });
      bar.append(cancelBtn);
      container.append(bar);
    }

    // NP Order + Optional Strategy row
    const npBox = document.createElement("div");
    npBox.className = "wizard-card-block wizard-np-row";
    const npHead = document.createElement("strong");
    npHead.textContent = t("NP Order");
    npBox.append(npHead);
    const npChips = document.createElement("div");
    npChips.className = "wizard-filter-row";
    for (let slot = 1; slot <= 3; slot += 1) {
      const sName = lineupServantName(activeLineup, slot - 1);
      const orderIdx = npList.indexOf(slot);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `chip-button${orderIdx >= 0 ? " active" : ""}`;
      btn.textContent = `${orderIdx >= 0 ? `#${orderIdx + 1} ` : ""}${sName ? `${slot}·${sName}` : t("Servant {slot}", { slot })} NP`;
      btn.addEventListener("click", () => {
        writeConfig((draft) => {
          draft[`round${wave}_turns`] = Math.max(1, Number(draft[`round${wave}_turns`] || 0));
          const cur = Array.isArray(draft[npKey]) ? [...draft[npKey]] : [];
          const idx = cur.indexOf(slot);
          if (idx >= 0) cur.splice(idx, 1);
          else cur.push(slot);
          draft[npKey] = cur;
        });
      });
      npChips.append(btn);
    }
    npBox.append(npChips);

    // Optional strategy selector
    const stratList = typeof getStrategies === "function" ? getStrategies() : [];
    if (stratList.length) {
      const stratRow = document.createElement("div");
      stratRow.className = "wizard-strategy-inline";
      const stratSel = document.createElement("select");
      stratSel.className = "field";
      const emptyOpt = document.createElement("option");
      emptyOpt.value = "";
      emptyOpt.textContent = t("Optional card strategy preset...");
      stratSel.append(emptyOpt);
      for (const st of stratList) {
        const opt = document.createElement("option");
        opt.value = st.name;
        opt.textContent = st.name;
        stratSel.append(opt);
      }
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "ghost-button";
      applyBtn.textContent = t("Apply");
      applyBtn.addEventListener("click", async () => {
        if (!stratSel.value) return;
        try {
          const detail = await request(`/api/strategies/${encodeURIComponent(stratSel.value)}`);
          if (detail?.validation?.ok === false) return;
          const unwrapped = (Array.isArray(detail?.entries) ? detail.entries : [])
            .map((entry) => (entry && typeof entry === "object" && !Array.isArray(entry) && entry.strategy && typeof entry.strategy === "object" ? entry.strategy : entry))
            .filter((item) => item && typeof item === "object" && !Array.isArray(item) && item.card1 && item.card2 && item.card3);
          if (!unwrapped.length) return;
          writeConfig((draft) => {
            draft[`round${wave}_turns`] = Math.max(1, Number(draft[`round${wave}_turns`] || 0));
            draft[stratKey] = unwrapped;
          });
        } catch {
          // Ignore failed strategy load.
        }
      });
      const currentStrat = Array.isArray(config[stratKey]) && config[stratKey].length
        ? t("{count} strategy entries applied", { count: config[stratKey].length })
        : "";
      stratRow.append(stratSel, applyBtn);
      if (currentStrat) {
        const badge = document.createElement("span");
        badge.className = "wizard-picker-count";
        badge.textContent = currentStrat;
        const clearStratBtn = document.createElement("button");
        clearStratBtn.type = "button";
        clearStratBtn.className = "chip-button";
        clearStratBtn.textContent = t("Clear");
        clearStratBtn.addEventListener("click", () => {
          writeConfig((draft) => { delete draft[stratKey]; });
        });
        stratRow.append(badge, clearStratBtn);
      }
      npBox.append(stratRow);
    }
    container.append(npBox);

    // Action Timeline
    const timeline = document.createElement("div");
    timeline.className = "wizard-card-block";
    const tlHead = document.createElement("div");
    tlHead.className = "wizard-section-head";
    tlHead.innerHTML = `<strong>${t("Wave {round} Action Queue", { round: wave })} (${skillList.length})</strong>`;
    if (skillList.length) {
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "chip-button";
      clearBtn.textContent = t("Clear");
      clearBtn.addEventListener("click", () => {
        writeConfig((draft) => { draft[skillKey] = []; });
      });
      tlHead.append(clearBtn);
    }
    timeline.append(tlHead);

    const chipsWrap = document.createElement("div");
    chipsWrap.className = "wizard-timeline-chips";
    if (!skillList.length) {
      const empty = document.createElement("div");
      empty.className = "wizard-empty-hint";
      empty.textContent = t("Click skill buttons above to build this wave's action sequence.");
      chipsWrap.append(empty);
    } else {
      const chipLineup = [...waveStartLineup];
      let chipCondDepth = 0;
      skillList.forEach((cmd, idx) => {
        const chip = document.createElement("span");
        chip.className = "wizard-action-chip";
        const chipIcon = resolveSkillChipIcon(cmd, config, servants, chipLineup);
        if (chipIcon) {
          chip.append(createAvatarImg(skillIconUrl(chipIcon), "", "wizard-chip-icon"));
        }
        const lbl = document.createElement("span");
        lbl.textContent = formatSkillChip(cmd, config, servants, chipLineup);
        const del = document.createElement("button");
        del.type = "button";
        del.textContent = "×";
        del.title = t("Remove skill");
        del.addEventListener("click", () => {
          writeConfig((draft) => {
            const arr = Array.isArray(draft[skillKey]) ? [...draft[skillKey]] : [];
            arr.splice(idx, 1);
            draft[skillKey] = arr;
          });
        });
        chip.append(lbl, del);
        chipsWrap.append(chip);
        if (Array.isArray(cmd) && cmd[0] === "Start") chipCondDepth += 1;
        else if (Array.isArray(cmd) && cmd[0] === "End") chipCondDepth = Math.max(0, chipCondDepth - 1);
        else if (chipCondDepth === 0) applyOrderChange(chipLineup, cmd);
      });
    }
    timeline.append(chipsWrap);
    container.append(timeline);
  }

  function resolveSkillChipIcon(cmd, config, servants = [], lineup = [0, 1, 2, 3, 4, 5]) {
    const svtNum = extractServantSkillNumber(cmd);
    if (svtNum !== null) {
      const pos = Math.floor((svtNum - 1) / 3);
      const sk = (svtNum - 1) % 3;
      const origSlot = lineup[pos];
      if (origSlot == null) return "";
      const info = findServant(servants, config[`servant_${origSlot}_name`]);
      return info?.skills?.[sk] || "";
    }
    const num = typeof cmd === "number" ? cmd : (Array.isArray(cmd) && typeof cmd[0] === "number" ? cmd[0] : null);
    if (num !== null && num >= 10 && num <= 12) {
      const mInfo = (state.masters || []).find((m) => String(m.sn) === String(config.master_equip));
      return mInfo?.skills?.[num - 10] || "";
    }
    return "";
  }

  function formatSkillChip(cmd, config, servants = [], lineup = [0, 1, 2, 3, 4, 5]) {
    const slotLabel = (pos) => {
      const origSlot = lineup[pos - 1];
      if (origSlot == null) return `S${pos}`;
      const nm = config[`servant_${origSlot}_name`];
      return nm ? `${pos}·${nm.slice(0, 6)}` : `S${pos}`;
    };
    const skillName = (num) => {
      if (num >= 1 && num <= 9) {
        const pos = Math.floor((num - 1) / 3) + 1;
        const sk = ((num - 1) % 3) + 1;
        const origSlot = lineup[pos - 1];
        const info = origSlot != null ? findServant(servants, config[`servant_${origSlot}_name`]) : null;
        const official = info?.skill_details?.[sk - 1]?.name;
        return official ? `${slotLabel(pos)} ${official}` : `${slotLabel(pos)} 技${sk}`;
      }
      if (num >= 10 && num <= 12) {
        const mInfo = (state.masters || []).find((m) => String(m.sn) === String(config.master_equip));
        const official = mInfo?.skill_details?.[num - 10]?.name;
        return official ? `${t("Master")} ${official}` : `${t("Master")} 技${num - 9}`;
      }
      if (num === 13) return t("Enemy target");
      return String(num);
    };
    const specialFormatted = formatSpecialSkillCommand(cmd, { skillName, slotLabel, translate: t });
    if (specialFormatted) return specialFormatted;
    if (typeof cmd === "number") return skillName(cmd);
    if (Array.isArray(cmd)) {
      if (cmd.length === 2 && cmd[0] === 13) {
        return `${t("Enemy target")} → ${t("Enemy {slot}", { slot: cmd[1] })}`;
      }
      if (cmd.length === 2 && cmd[0] === "\u4ee4\u5492\u00b7\u5b9d\u5177\u89e3\u653e") {
        return `${t("Command Spell / NP Charge")} → ${slotLabel(cmd[1])}`;
      }
      if (cmd.length === 2 && cmd[0] === "\u4ee4\u5492\u00b7\u7075\u57fa\u4fee\u590d") {
        return `${t("Command Spell / Heal")} → ${slotLabel(cmd[1])}`;
      }
      if (cmd.length === 3 && cmd[0] >= 10 && cmd[0] <= 12) {
        return `${t("Order Change")} ${slotLabel(cmd[1])}↔${slotLabel(cmd[2])}`;
      }
      if (cmd.length >= 2 && typeof cmd[0] === "number") {
        return `${skillName(cmd[0])} → ${slotLabel(cmd[1])}`;
      }
    }
    return JSON.stringify(cmd);
  }

  function renderStep4Review(container, config, servants, server) {
    const card = document.createElement("div");
    card.className = "wizard-card-block";
    const head = document.createElement("div");
    head.className = "wizard-section-head";
    head.innerHTML = `<strong>${t("Summary & Settlement Preferences")}</strong>`;
    const autoNameBtn = document.createElement("button");
    autoNameBtn.type = "button";
    autoNameBtn.className = "chip-button";
    autoNameBtn.textContent = t("Auto-name from Team");
    autoNameBtn.addEventListener("click", () => {
      const suggested = buildSuggestedName(config);
      if (suggested) {
        nameInput.value = suggested;
        state.autoNamedValue = suggested;
      }
    });
    head.append(autoNameBtn);
    card.append(head);

    // Compact team + Master outfit + Assist CE preview strip
    const teamStrip = document.createElement("div");
    teamStrip.className = "wizard-review-team";
    for (let i = 0; i < 6; i += 1) {
      const name = config[`servant_${i}_name`];
      if (!name) continue;
      const info = findServant(servants, name);
      const pill = document.createElement("div");
      pill.className = "wizard-review-servant";
      pill.append(createAvatarImg(servantPortraitUrl(info?.name || name, server, info?.face_index), name, "wizard-mini-avatar"));
      const txt = document.createElement("span");
      txt.textContent = `${i + 1}·${name}${config.assistIdx === i ? ` (${t("Support")})` : ""}`;
      pill.append(txt);
      teamStrip.append(pill);
    }
    if (config.master_equip != null && String(config.master_equip) !== "") {
      const mSn = String(config.master_equip);
      const mInfo = (state.masters || []).find((m) => String(m.sn) === mSn);
      const mSex = config.master_sex === 1 ? 1 : 0;
      const mPill = document.createElement("div");
      mPill.className = "wizard-review-servant wizard-review-master";
      mPill.append(createAvatarImg(masterPortraitUrl(mSn, mSex), mInfo?.name || mSn, "wizard-mini-avatar"));
      const mTxt = document.createElement("span");
      mTxt.textContent = `${t("Master")}: ${mInfo?.name || mSn}`;
      mPill.append(mTxt);
      teamStrip.append(mPill);
    }
    if (!["不识别", "仅从者"].includes(config.assistMode || "从者礼装")) {
      const flatCes = normalizeAssistEquipArray(config.assistEquip, false);
      for (const ceName of flatCes) {
        const cePill = document.createElement("div");
        cePill.className = "wizard-review-servant wizard-review-ce";
        if ((state.equips || []).includes(ceName)) {
          cePill.append(createAvatarImg(`/api/equip-templates/${encodeURIComponent(ceName)}/image?location=active`, ceName, "wizard-ce-thumb"));
        }
        const ceTxt = document.createElement("span");
        ceTxt.textContent = ceName;
        cePill.append(ceTxt);
        teamStrip.append(cePill);
      }
    }
    if (!teamStrip.children.length) {
      teamStrip.innerHTML = `<span class="wizard-empty-hint">${t("No servants selected yet.")}</span>`;
    }
    card.append(teamStrip);

    // Wave summary
    const waveSummary = document.createElement("div");
    waveSummary.className = "wizard-review-waves";
    const wc = extractWaveCount(config);
    for (let w = 1; w <= wc; w += 1) {
      const sks = Array.isArray(config[`round${w}_turn0_skill`]) ? config[`round${w}_turn0_skill`] : [];
      const nps = Array.isArray(config[`round${w}_turn0_np`]) ? config[`round${w}_turn0_np`] : [];
      const line = document.createElement("div");
      line.className = "wizard-review-wave-line";
      const reviewLineup = computeLineupBefore(config, w, 0);
      let reviewCondDepth = 0;
      const skText = sks.map((c) => {
        const text = formatSkillChip(c, config, servants, reviewLineup);
        if (Array.isArray(c) && c[0] === "Start") reviewCondDepth += 1;
        else if (Array.isArray(c) && c[0] === "End") reviewCondDepth = Math.max(0, reviewCondDepth - 1);
        else if (reviewCondDepth === 0) applyOrderChange(reviewLineup, c);
        return text;
      }).join(" → ") || t("No skills");
      const npText = nps.length ? `NP: ${nps.join(", ")}` : t("No NP");
      line.textContent = `${t("Wave {round}", { round: w })}: ${skText} | ${npText}`;
      waveSummary.append(line);
    }
    card.append(waveSummary);

    // 5 Practical toggles
    const toggles = document.createElement("div");
    toggles.className = "wizard-toggle-grid";
    for (const [key, labelKey] of [
      ["fullFriendshipStop", "Stop on full bond"],
      ["gameCrushRestart", "Crash restart"],
      ["firstBattleSet", "First battle setup"],
      ["clearAP", "Clear remaining AP"],
      ["allowOtherApple", "Allow other apples"],
    ]) {
      const lbl = document.createElement("label");
      lbl.className = "checkline";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = Boolean(config[key]);
      cb.addEventListener("change", () => {
        writeConfig((draft) => { draft[key] = cb.checked ? 1 : 0; });
      });
      const sp = document.createElement("span");
      sp.textContent = t(labelKey);
      lbl.append(cb, sp);
      toggles.append(lbl);
    }
    card.append(toggles);

    const proHint = document.createElement("div");
    proHint.className = "wizard-pro-hint";
    const proBtn = document.createElement("button");
    proBtn.type = "button";
    proBtn.className = "ghost-button";
    proBtn.textContent = t("Switch to Pro Mode for Advanced Edits");
    proBtn.addEventListener("click", () => onSwitchToPro());
    proHint.append(proBtn);
    card.append(proHint);

    container.append(card);
  }

  function renderNavFooter(container) {
    const footer = document.createElement("div");
    footer.className = "wizard-nav-footer";
    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "ghost-button";
    prevBtn.textContent = t("Previous");
    prevBtn.disabled = state.step === 0;
    prevBtn.addEventListener("click", () => {
      state.step = Math.max(0, state.step - 1);
      state.pendingTargetSkill = null;
      render();
    });
    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "primary-button";
    nextBtn.textContent = t("Next Step");
    nextBtn.hidden = state.step >= 3;
    nextBtn.addEventListener("click", () => {
      state.step = Math.min(3, state.step + 1);
      state.pendingTargetSkill = null;
      render();
    });
    footer.append(prevBtn, nextBtn);
    container.append(footer);
  }

  function render() {
    const editor = getEditor();
    const visible = Boolean(editor && editor.kind === "settings" && editor.uiMode === "wizard");
    root.hidden = !visible;
    if (!visible) return;

    ensureWizardDefaultsForNewScript();
    const config = readConfig();
    const server = ["CH", "CNTW", "JP"].includes(String(config.server || "").toUpperCase())
      ? String(config.server).toUpperCase()
      : "CH";
    void ensureCatalogs(server);
    const servants = state.servantsByServer.get(server) || [];

    const frag = document.createDocumentFragment();
    renderStepper(frag);
    const body = document.createElement("div");
    body.className = "wizard-body";
    if (state.step === 0) renderStep1Team(body, config, servants, server);
    else if (state.step === 1) renderStep2Assist(body, config, servants, server);
    else if (state.step === 2) renderStep3Timeline(body, config, servants, server);
    else renderStep4Review(body, config, servants, server);
    frag.append(body);
    renderNavFooter(frag);
    root.replaceChildren(frag);
  }

  function reset() {
    state.step = 0;
    state.activeSlot = 0;
    state.starFilter = "all";
    state.classFilter = "all";
    state.npFilter = "all";
    state.searchQuery = "";
    state.masterSearchQuery = "";
    state.masterFilter = "all";
    state.ceSearchQuery = "";
    state.grandCeSlot = 0;
    state.activeWave = 1;
    state.pendingTargetSkill = null;
    state.autoNamedValue = "";
    state.equips = null;
    state.equipsError = false;
  }

  return { render, reset };
}
