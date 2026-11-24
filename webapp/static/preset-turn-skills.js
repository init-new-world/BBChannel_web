import { t } from "./i18n.js";
import { COMMAND_SPELLS, decodeBasicSkill, isCommandSpell, MAX_SKILL_COMMANDS } from "./turn-skills-model.js";
import { decodeConditionCommand } from "./turn-conditions-model.js";
import { changeMixedSkillSource, inspectConditionSource, inspectMixedSkillSource } from "./turn-conditions-source.js";
import { describeConditionEntry } from "./preset-turn-conditions.js";
import { specialSkillChoice, specialSkillColors } from "./special-skills-model.js";
import { KUKULKAN_SKILL, kukulkanNeedsTarget } from "./kukulkan-model.js";
import { THIRD_SKILL_NAMES, thirdSkillOptions } from "./third-skill-model.js";
import { SKILL_VARIANT_NAMES, skillVariantAvailable, skillVariantNumbers, skillVariantOptions } from "./skill-variants-model.js";
import { readJsonField } from "./json-source.js";
import { HAKUNO_SKILL } from "./hakuno-needs-model.js";
import { createHakunoNeedsControls } from "./preset-hakuno-needs.js";

const HAKUNO_NEEDS_PREFIX = "HakunoNeeds:";

const THIRD_SKILL_LABELS = { Barghest: "UDK-Barghest", BBDubai: "BB Dubai", Soujyuro: "Soujyuro", Hakuno: "Hakuno" };
const THIRD_OPTION_LABELS = { Q: "Quick", A: "Arts", B: "Buster", T: "Sky", D: "Earth", R: "Human" };
const VARIANT_LABELS = { VanGoghMiner: "Van Gogh (Miner)", Dante: "Dante", Gyokuto: "Gyokuto", Charlotte: "Charlotte Corday", Flora: "Flora" };
const VARIANT_OPTION_LABELS = {
  VanGoghMiner: { Q: "Quick", A: "Arts", B: "Buster" },
  Dante: { A: "Paradiso (Arts Up)", B: "Inferno (Buster Up)" },
  Gyokuto: { All: "Moonlight (AoE NP)", One: "Sun (Single-Target NP)" },
  Charlotte: { "\u6280": "Skill Up", "\u66b4": "Critical Damage Up", "\u5b9d": "NP Damage Up" },
  Flora: { T: "Normal", D: "Underworld Garden" },
};

function namedOptions(named) {
  return thirdSkillOptions(named) || skillVariantOptions(named);
}

function variantServer(source) {
  try {
    return readJsonField(source, "server", "Ambiguous server field.").value;
  } catch {
    return null;
  }
}

export function createPresetTurnSkillsEditor({ getEditor, source, readTarget, validateConfig, onChange, onError }) {
  const section = document.querySelector("#preset-turn-skills");
  const controls = document.querySelector("#preset-turn-skill-controls");
  const list = document.querySelector("#preset-turn-skill-list");
  const status = document.querySelector("#preset-turn-skill-status");
  const count = document.querySelector("#preset-turn-skill-count");
  const add = document.querySelector("#add-turn-skill");
  const addConditionStart = document.querySelector("#add-turn-condition-start");
  const addConditionEnd = document.querySelector("#add-turn-condition-end");
  const clear = document.querySelector("#clear-turn-skills");
  const hakunoControls = createHakunoNeedsControls();
  let rendered = null;

  function option(value, label) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    return node;
  }

  function servantSlotName(config, slot) {
    const raw = config?.[`servant_${slot - 1}_name`];
    return typeof raw === "string" && raw.trim() ? raw.trim() : "";
  }

  function servantSlotLabel(config, slot) {
    const name = servantSlotName(config, slot);
    return name ? `${slot}·${name}` : t("Servant {slot}", { slot });
  }

  function positionSelect(part, label, slots, value, config = null) {
    const select = document.createElement("select");
    select.className = "field";
    select.dataset.turnSkillPart = part;
    select.setAttribute("aria-label", t(label));
    for (const slot of slots) select.append(option(String(slot), servantSlotLabel(config, slot)));
    select.value = String(value);
    select.title = `${t(label)}: ${select.selectedOptions[0].textContent}`;
    return select;
  }

  function buildSkillTools(index, length) {
    const tools = document.createElement("div");
    tools.className = "turn-skill-tools";
    for (const [action, icon, label, disabled] of [
      ["up", "arrow-up", "Move skill up", index === 0],
      ["down", "arrow-down", "Move skill down", index === length - 1],
      ["remove", "trash-2", "Remove skill", false],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "icon-button";
      button.dataset.turnSkillAction = action;
      button.title = t(label);
      button.setAttribute("aria-label", t(label));
      button.disabled = disabled;
      const image = document.createElement("img");
      image.src = `/icons/${icon}.svg`;
      image.width = image.height = 16;
      image.alt = "";
      button.append(image);
      tools.append(button);
    }
    return tools;
  }

  function conditionStartRow(decoded, index, length, { conditionEntries }) {
    const item = document.createElement("div");
    item.className = "turn-skill-row turn-skill-condition-start";
    item.dataset.turnSkillIndex = String(index);
    item.setAttribute("role", "group");
    item.setAttribute("aria-label", t("Condition Start"));

    const body = document.createElement("div");
    body.className = "condition-start-body";

    const header = document.createElement("div");
    header.className = "condition-start-header";
    const title = document.createElement("span");
    title.className = "condition-start-title";
    title.textContent = t("Condition Start");
    const mode = document.createElement("select");
    mode.className = "field";
    mode.dataset.turnSkillPart = "condition-mode";
    mode.setAttribute("aria-label", t("Condition mode"));
    mode.append(option("1", t("Run when matched")), option("0", t("Skip when matched")));
    mode.value = String(decoded.mode);
    header.append(title, mode);
    body.append(header);

    const checkCount = Math.max(conditionEntries.length, decoded.checks.length);
    if (checkCount > 0) {
      const checks = document.createElement("div");
      checks.className = "condition-start-checks";
      for (let checkIdx = 0; checkIdx < checkCount; checkIdx += 1) {
        const label = document.createElement("label");
        label.className = "checkline";
        if (conditionEntries[checkIdx]) {
          label.title = describeConditionEntry(conditionEntries[checkIdx], checkIdx);
        }
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.dataset.turnSkillPart = "condition-check";
        checkbox.dataset.conditionCheckIndex = String(checkIdx);
        checkbox.checked = Boolean(decoded.checks[checkIdx]);
        const text = document.createElement("span");
        text.textContent = t("Cond #{index}", { index: checkIdx + 1 });
        label.append(checkbox, text);
        checks.append(label);
      }
      body.append(checks);
    }

    const npContainer = document.createElement("div");
    npContainer.className = "condition-start-np";
    decoded.npChecks.forEach((entry, slotIdx) => {
      const slot = document.createElement("div");
      slot.className = "condition-np-slot";
      slot.dataset.conditionNpSlot = String(slotIdx);

      const label = document.createElement("label");
      label.className = "checkline";
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.dataset.turnSkillPart = "condition-np-enabled";
      enabled.checked = entry.enabled;
      const text = document.createElement("span");
      text.textContent = t("NP {slot}", { slot: slotIdx + 1 });
      label.append(enabled, text);

      const op = document.createElement("select");
      op.className = "field";
      op.dataset.turnSkillPart = "condition-np-op";
      op.setAttribute("aria-label", t("NP comparison for servant {slot}", { slot: slotIdx + 1 }));
      op.append(option("≥", "≥"), option("≤", "≤"));
      op.value = entry.op;

      const valueInput = document.createElement("input");
      valueInput.type = "number";
      valueInput.className = "field";
      valueInput.min = "0";
      valueInput.max = "300";
      valueInput.step = "1";
      valueInput.dataset.turnSkillPart = "condition-np-value";
      valueInput.setAttribute("aria-label", t("NP percentage for servant {slot}", { slot: slotIdx + 1 }));
      valueInput.value = String(entry.value);

      slot.append(label, op, valueInput);
      npContainer.append(slot);
    });
    body.append(npContainer);

    item.append(body, buildSkillTools(index, length));
    return item;
  }

  function conditionEndRow(index, length) {
    const item = document.createElement("div");
    item.className = "turn-skill-row turn-skill-condition-end";
    item.dataset.turnSkillIndex = String(index);
    item.setAttribute("role", "group");
    item.setAttribute("aria-label", t("Condition End"));
    const title = document.createElement("span");
    title.className = "condition-start-title";
    title.textContent = t("Condition End");
    item.append(title, buildSkillTools(index, length));
    return item;
  }

  function row(command, index, length, context) {
    const conditionCommand = decodeConditionCommand(command);
    if (conditionCommand?.kind === "condition-start") {
      return conditionStartRow(conditionCommand, index, length, context);
    }
    if (conditionCommand?.kind === "condition-end") {
      return conditionEndRow(index, length);
    }
    const { server, config, field, editor } = context;
    const value = decodeBasicSkill(command);
    const item = document.createElement("div");
    item.className = "turn-skill-row";
    item.classList.toggle("turn-skill-exchange", Boolean(value.swap));
    item.classList.toggle("turn-skill-color", value.choice !== undefined);
    item.classList.toggle("turn-skill-named", Boolean(value.named));
    item.classList.toggle("turn-skill-hakuno", value.needs !== undefined);
    item.dataset.turnSkillIndex = String(index);
    item.setAttribute("role", "group");
    item.setAttribute("aria-label", t("Skill {index}", { index: index + 1 }));
    const skill = document.createElement("select");
    skill.className = "field";
    skill.dataset.turnSkillPart = "skill";
    skill.setAttribute("aria-label", t("Skill {index}", { index: index + 1 }));
    for (let number = 1; number <= 13; number += 1) {
      let label;
      if (number <= 9) {
        const slot = Math.floor((number - 1) / 3) + 1;
        const skillNum = (number - 1) % 3 + 1;
        const name = servantSlotName(config, slot);
        label = name
          ? `${slot}·${name} / ${t("Skill {index}", { index: skillNum })}`
          : t("Servant {slot} / Skill {skill}", { slot, skill: skillNum });
      } else if (number <= 12) {
        label = t("Master / Skill {skill}", { skill: number - 9 });
      } else {
        label = t("Enemy target");
      }
      skill.append(option(String(number), label));
    }
    for (let number = 10; number <= 12; number += 1) {
      skill.append(option(`swap:${number}`, t("Order change / Skill {skill}", { skill: number - 9 })));
    }
    for (const [kind, spell] of Object.entries(COMMAND_SPELLS)) {
      skill.append(option(spell, t(kind === "np" ? "Command Spell / NP Charge" : "Command Spell / Heal")));
    }
    for (let slot = 1; slot <= 3; slot += 1) {
      for (const number of [2, 3]) {
        skill.append(option(String(-((slot - 1) * 3 + number)), t("NP Color / Servant {slot} / Skill {skill}", { slot, skill: number })));
      }
    }
    for (let number = 1; number <= 9; number += 1) {
      skill.append(option(`${KUKULKAN_SKILL}:${number}`, t("Kukulkan / Servant {slot} / Skill {skill}", {
        slot: Math.floor((number - 1) / 3) + 1, skill: (number - 1) % 3 + 1,
      })));
    }
    for (const named of THIRD_SKILL_NAMES) {
      for (const number of [3, 6, 9]) {
        skill.append(option(`${named}:${number}`, t("{name} / Servant {slot} / Skill 3", {
          name: t(THIRD_SKILL_LABELS[named]), slot: number / 3,
        })));
      }
    }
    for (const named of SKILL_VARIANT_NAMES) {
      for (const number of skillVariantNumbers(named)) {
        const labels = {
          name: t(VARIANT_LABELS[named]), slot: Math.floor((number - 1) / 3) + 1, skill: (number - 1) % 3 + 1,
        };
        const entry = option(`${named}:${number}`, t("{name} / Slot {slot} / Skill {skill}", labels));
        entry.title = t("{name} / Servant {slot} / Skill {skill}", labels);
        entry.disabled = !skillVariantAvailable(named, server);
        skill.append(entry);
      }
    }
    for (const number of [1, 4, 7]) {
      skill.append(option(`${HAKUNO_NEEDS_PREFIX}${number}`, t("Hakuno Cards / Slot {slot} / Skill 1", { slot: (number + 2) / 3 })));
    }
    skill.value = value.needs !== undefined ? `${HAKUNO_NEEDS_PREFIX}${value.skill}`
      : value.named ? `${value.named}:${value.skill}` : value.swap ? `swap:${value.skill}` : String(value.skill);
    skill.title = skill.selectedOptions[0].title || skill.selectedOptions[0].textContent;
    let target;
    if (value.needs !== undefined) {
      target = hakunoControls.render({ needs: value.needs, index, field, config, editor });
    } else if (value.swap) {
      target = document.createElement("div");
      target.className = "turn-skill-exchange-targets";
      for (const [part, label, slots, position] of [
        ["front", "Frontline", [1, 2, 3], value.swap.find((slot) => slot <= 3)],
        ["reserve", "Reserve", [4, 5, 6], value.swap.find((slot) => slot > 3)],
      ]) {
        const field = document.createElement("label");
        field.className = "field-stack";
        const heading = document.createElement("span");
        heading.textContent = t(label);
        field.append(heading, positionSelect(part, label, slots, position, config));
        target.append(field);
      }
    } else if (value.named === KUKULKAN_SKILL || value.named === "Barghest") {
      target = document.createElement("div");
      target.className = "turn-skill-named-controls";
      const label = document.createElement("label");
      label.className = "checkline";
      label.title = t(value.named === KUKULKAN_SKILL ? "Spend 10 critical stars" : "Single Target");
      const useStars = document.createElement("input");
      useStars.type = "checkbox";
      useStars.dataset.turnSkillPart = "named-option";
      useStars.checked = value.option === 1;
      const text = document.createElement("span");
      text.textContent = t(value.named === KUKULKAN_SKILL ? "Use 10 Stars" : "Single Target");
      label.append(useStars, text);
      target.append(label);
      if (value.named === KUKULKAN_SKILL && kukulkanNeedsTarget(value.skill)) {
        target.append(positionSelect("target", "Skill target", [1, 2, 3], value.target, config));
      }
    } else if (value.named) {
      target = document.createElement("div");
      target.className = "turn-skill-named-controls";
      if (value.named === "BBDubai") {
        const modes = document.createElement("div");
        modes.className = "segmented-control";
        modes.setAttribute("role", "group");
        modes.setAttribute("aria-label", t("Skill option"));
        for (const [number, label] of [[0, "Attack Type"], [1, "Defense Type"]]) {
          const mode = document.createElement("button");
          mode.type = "button";
          mode.className = "segment";
          mode.classList.toggle("active", value.option === number);
          mode.dataset.turnSkillPart = `named-option-${number}`;
          mode.dataset.turnSkillOption = String(number);
          mode.setAttribute("aria-pressed", String(value.option === number));
          mode.textContent = mode.title = t(label);
          modes.append(mode);
        }
        target.append(modes);
      } else {
        const choice = document.createElement("select");
        choice.className = "field";
        choice.dataset.turnSkillPart = "named-option";
        choice.setAttribute("aria-label", t("Skill option"));
        const labels = VARIANT_OPTION_LABELS[value.named] || THIRD_OPTION_LABELS;
        for (const optionValue of namedOptions(value.named)) {
          choice.append(option(optionValue, t(labels[optionValue])));
        }
        choice.value = value.option;
        choice.title = choice.selectedOptions[0].textContent;
        if (["Soujyuro", "VanGoghMiner", "Dante"].includes(value.named)) {
          const swatch = document.createElement("span");
          swatch.className = "np-color-swatch";
          swatch.dataset.color = THIRD_OPTION_LABELS[value.option];
          swatch.setAttribute("aria-hidden", "true");
          target.append(swatch);
        }
        target.append(choice);
      }
    } else if (value.choice !== undefined) {
      target = document.createElement("div");
      target.className = "turn-skill-color-choice";
      const colors = specialSkillColors(value.skill);
      const swatch = document.createElement("span");
      swatch.className = "np-color-swatch";
      swatch.dataset.color = colors[value.choice - 1];
      swatch.setAttribute("aria-hidden", "true");
      const choice = document.createElement("select");
      choice.className = "field";
      choice.dataset.turnSkillPart = "choice";
      choice.setAttribute("aria-label", t("NP color"));
      colors.forEach((color, index) => choice.append(option(String(index + 1), t(color))));
      choice.value = String(value.choice);
      choice.title = choice.selectedOptions[0].textContent;
      target.append(swatch, choice);
    } else {
      target = document.createElement("select");
      target.className = "field";
      target.dataset.turnSkillPart = "target";
      const enemy = value.skill === 13;
      const spell = isCommandSpell(value.skill);
      target.setAttribute("aria-label", t(enemy ? "Enemy target" : spell ? "Command spell target" : "Skill target"));
      if (!enemy && !spell) target.append(option("", t("No target")));
      for (let slot = 1; slot <= (enemy ? 6 : 3); slot += 1) {
        target.append(option(String(slot), enemy ? t("Enemy {slot}", { slot }) : servantSlotLabel(config, slot)));
      }
      target.value = value.target === null ? "" : String(value.target);
      target.title = target.selectedOptions[0].textContent;
    }
    item.append(skill, target, buildSkillTools(index, length));
    return item;
  }

  function render(target) {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    if (editor?.kind === "settings" && !editor.turnSkillsInitialized) {
      section.open = false;
      editor.turnSkillsInitialized = true;
    }
    try {
      if (editor?.kind !== "settings" || !target) throw new Error("No turn selected");
      if (rendered?.editor !== editor || rendered.source !== source.value || rendered.target !== target) {
        const config = JSON.parse(source.value);
        validateConfig(config);
        const info = inspectMixedSkillSource(source.value, target);
        const server = variantServer(source.value);
        let conditionEntries = [];
        try {
          conditionEntries = inspectConditionSource(source.value, target).entries || [];
        } catch {
          conditionEntries = [];
        }
        const context = { server, config, field: target, editor, conditionEntries };
        list.replaceChildren(...(info.commands || []).map((command, index) => row(command, index, info.commands.length, context)));
        rendered = { editor, source: source.value, target, info };
      }
      controls.disabled = Boolean(editor.saving || editor.strategyApplyBusy);
      const atLimit = rendered.info.commands === null || rendered.info.commands.length >= MAX_SKILL_COMMANDS;
      add.disabled = addConditionStart.disabled = addConditionEnd.disabled = atLimit;
      clear.disabled = !rendered.info.canClear;
      count.textContent = rendered.info.commands === null ? "" : String(rendered.info.commands.length);
      status.textContent = rendered.info.error ? t(rendered.info.error) : "";
      status.hidden = !status.textContent;
    } catch (error) {
      rendered = null;
      controls.disabled = true;
      add.disabled = addConditionStart.disabled = addConditionEnd.disabled = clear.disabled = true;
      list.replaceChildren();
      count.textContent = "";
      status.textContent = t(error.message);
      status.hidden = false;
    }
  }

  function edit(change, focusIndex = -1, part = "skill") {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled) return;
    try {
      const { config, field } = readTarget();
      validateConfig(config);
      if (rendered?.editor !== editor || rendered.source !== source.value || rendered.target !== field) {
        throw new Error("Skill sequence changed.");
      }
      if (change.type === "needs-group" || change.type === "needs-action") {
        const value = decodeBasicSkill(rendered.info.commands?.[change.index]);
        if (value?.needs === undefined) throw new Error("Skill sequence changed.");
        const context = { needs: value.needs, index: change.index, field, config, editor };
        if (change.type === "needs-group") {
          hakunoControls.select(context, change.group);
          list.querySelector(`[data-turn-skill-index="${change.index}"] .turn-skill-hakuno-controls`)
            .replaceWith(hakunoControls.render(context));
        } else {
          const result = hakunoControls.change(context, change);
          part = result.part;
          source.value = changeMixedSkillSource(source.value, field, { type: "update", index: change.index, named: HAKUNO_SKILL, skill: value.skill, needs: result.needs });
          onChange();
        }
      } else {
        if (["move", "remove", "clear"].includes(change.type)) hakunoControls.forget(field);
        if (change.needs !== undefined) hakunoControls.activate(field, change.index, editor);
        source.value = changeMixedSkillSource(source.value, field, change);
        onChange();
      }
      if (getEditor() !== editor) return;
      const item = list.querySelector(`[data-turn-skill-index="${Math.max(focusIndex, 0)}"]`)
        || list.lastElementChild;
      const focus = item?.querySelector(`[data-turn-skill-part="${part}"]`) || add;
      focus.focus({ preventScroll: true });
      if (part.startsWith("needs-")) focus.scrollIntoView({ block: "nearest" });
    } catch (error) {
      onError(t(error.message));
    }
  }

  add.addEventListener("click", () => {
    if (!add.disabled) edit({ type: "add" }, rendered?.info.commands?.length || 0);
  });
  addConditionStart.addEventListener("click", () => {
    if (addConditionStart.disabled) return;
    let conditionEntries = [];
    try {
      conditionEntries = inspectConditionSource(source.value, readTarget().field).entries || [];
    } catch {
      conditionEntries = [];
    }
    edit(
      { type: "add-condition-start", mode: 1, checks: conditionEntries.map(() => 0) },
      rendered?.info.commands?.length || 0,
      "condition-mode",
    );
  });
  addConditionEnd.addEventListener("click", () => {
    if (!addConditionEnd.disabled) edit({ type: "add-condition-end" }, rendered?.info.commands?.length || 0);
  });
  clear.addEventListener("click", () => {
    if (!clear.disabled && !controls.disabled && window.confirm(t("Clear the selected skill sequence?"))) edit({ type: "clear" });
  });
  list.addEventListener("change", (event) => {
    const control = event.target.closest("select[data-turn-skill-part], input[data-turn-skill-part]");
    const item = control?.closest("[data-turn-skill-index]");
    if (!item || control.selectedOptions?.[0]?.disabled) return;
    const index = Number(item.dataset.turnSkillIndex);
    if (item.classList.contains("turn-skill-condition-start")) {
      const part = control.dataset.turnSkillPart;
      const mode = Number(item.querySelector('[data-turn-skill-part="condition-mode"]').value);
      const checks = [...item.querySelectorAll('input[data-turn-skill-part="condition-check"]')]
        .sort((a, b) => Number(a.dataset.conditionCheckIndex) - Number(b.dataset.conditionCheckIndex))
        .map((entry) => (entry.checked ? 1 : 0));
      const npChecks = [...item.querySelectorAll(".condition-np-slot")].map((slot) => ({
        enabled: slot.querySelector('[data-turn-skill-part="condition-np-enabled"]').checked,
        op: slot.querySelector('[data-turn-skill-part="condition-np-op"]').value,
        value: slot.querySelector('[data-turn-skill-part="condition-np-value"]').valueAsNumber,
      }));
      const includeNp = npChecks.some((entry) => entry.enabled)
        || part === "condition-np-op"
        || part === "condition-np-value";
      edit({ type: "update-condition-start", index, mode, checks, npChecks, includeNp }, index, part);
      return;
    }
    const selection = item.querySelector('[data-turn-skill-part="skill"]').value;
    const needsMode = selection.startsWith(HAKUNO_NEEDS_PREFIX);
    const named = [KUKULKAN_SKILL, ...THIRD_SKILL_NAMES, ...SKILL_VARIANT_NAMES].find((name) => selection.startsWith(`${name}:`));
    const exchange = selection.startsWith("swap:");
    const spell = isCommandSpell(selection);
    const skill = needsMode ? Number(selection.slice(HAKUNO_NEEDS_PREFIX.length)) : named ? Number(selection.slice(named.length + 1))
      : exchange ? Number(selection.slice(5)) : spell ? selection : Number(selection);
    const previous = decodeBasicSkill(rendered?.info.commands?.[index]);
    if (needsMode) {
      const part = control.dataset.turnSkillPart;
      if (part === "skill") edit({ type: "update", index, named: HAKUNO_SKILL, skill, needs: previous?.needs ?? [] }, index);
      else if (part === "needs-group") edit({ type: "needs-group", index, group: Number(control.value) }, index, part);
      else if (part.startsWith("needs-card-")) edit({ type: "needs-action", index, action: "update-card", card: Number(part.slice(11)), code: control.value }, index, part);
      return;
    }
    if (named === KUKULKAN_SKILL) {
      const sameKind = previous?.named === KUKULKAN_SKILL;
      const changingSkill = control.dataset.turnSkillPart === "skill";
      const option = changingSkill ? sameKind ? previous.option : 0
        : item.querySelector('input[data-turn-skill-part="named-option"]')?.checked ? 1 : 0;
      const target = !kukulkanNeedsTarget(skill) ? null : changingSkill
        ? sameKind && previous.target !== null ? previous.target : 1
        : Number(item.querySelector('select[data-turn-skill-part="target"]')?.value || 1);
      edit({ type: "update", index, named: KUKULKAN_SKILL, skill, option, target }, index, control.dataset.turnSkillPart);
      return;
    }
    if (named) {
      const option = control.dataset.turnSkillPart === "skill"
        ? previous?.named === named && previous.needs === undefined ? previous.option : namedOptions(named)[0]
        : named === "Barghest" ? control.checked ? 1 : 0 : control.value;
      edit({ type: "update", index, named, skill, option }, index, control.dataset.turnSkillPart);
      return;
    }
    if (specialSkillColors(skill)) {
      const choice = control.dataset.turnSkillPart === "skill"
        ? specialSkillChoice(rendered?.info.commands?.[index], skill)
        : Number(item.querySelector('[data-turn-skill-part="choice"]').value);
      edit({ type: "update", index, skill, choice }, index, control.dataset.turnSkillPart);
      return;
    }
    if (exchange) {
      const swap = control.dataset.turnSkillPart === "skill" ? previous?.swap || [1, 4]
        : [Number(item.querySelector('[data-turn-skill-part="front"]').value),
          Number(item.querySelector('[data-turn-skill-part="reserve"]').value)];
      edit({ type: "update", index, skill, swap }, index, control.dataset.turnSkillPart);
      return;
    }
    const selectedTarget = item.querySelector('[data-turn-skill-part="target"]')?.value || "";
    let target = selectedTarget === "" ? null : Number(selectedTarget);
    if (control.dataset.turnSkillPart === "skill" && previous
        && (previous.named || previous.swap || previous.choice !== undefined || (previous.skill === 13) !== (skill === 13) || isCommandSpell(previous.skill) !== spell)) {
      target = skill === 13 || spell ? 1 : null;
    }
    edit({ type: "update", index, skill, target }, index, control.dataset.turnSkillPart);
  });
  list.addEventListener("click", (event) => {
    const needs = event.target.closest("button[data-hakuno-needs-action]");
    if (needs) {
      if (needs.disabled) return;
      const index = Number(needs.closest("[data-turn-skill-index]").dataset.turnSkillIndex);
      edit({ type: "needs-action", index, action: needs.dataset.hakunoNeedsAction,
        card: needs.dataset.hakunoCardIndex === undefined ? undefined : Number(needs.dataset.hakunoCardIndex) }, index);
      return;
    }
    const option = event.target.closest("button[data-turn-skill-option]");
    if (option) {
      if (option.disabled) return;
      const index = Number(option.closest("[data-turn-skill-index]").dataset.turnSkillIndex);
      const previous = decodeBasicSkill(rendered?.info.commands?.[index]);
      if (previous?.named === "BBDubai") {
        edit({ type: "update", index, named: previous.named, skill: previous.skill, option: Number(option.dataset.turnSkillOption) },
          index, option.dataset.turnSkillPart);
      }
      return;
    }
    const button = event.target.closest("button[data-turn-skill-action]");
    if (!button || button.disabled) return;
    const index = Number(button.closest("[data-turn-skill-index]").dataset.turnSkillIndex);
    const action = button.dataset.turnSkillAction;
    if (action === "remove") edit({ type: "remove", index }, index);
    else edit({ type: "move", index, to: index + (action === "up" ? -1 : 1) }, index + (action === "up" ? -1 : 1));
  });
  return { render };
}
