import { t } from "./i18n.js";
import { decodeBasicSkill, MAX_SKILL_COMMANDS } from "./turn-skills-model.js";
import { changeSkillSource, inspectSkillSource } from "./turn-skills-source.js";

export function createPresetTurnSkillsEditor({ getEditor, source, readTarget, validateConfig, onChange, onError }) {
  const section = document.querySelector("#preset-turn-skills");
  const controls = document.querySelector("#preset-turn-skill-controls");
  const list = document.querySelector("#preset-turn-skill-list");
  const status = document.querySelector("#preset-turn-skill-status");
  const count = document.querySelector("#preset-turn-skill-count");
  const add = document.querySelector("#add-turn-skill");
  const clear = document.querySelector("#clear-turn-skills");
  let rendered = null;

  function option(value, label) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    return node;
  }

  function positionSelect(part, label, slots, value) {
    const select = document.createElement("select");
    select.className = "field";
    select.dataset.turnSkillPart = part;
    select.setAttribute("aria-label", t(label));
    for (const slot of slots) select.append(option(String(slot), t("Servant {slot}", { slot })));
    select.value = String(value);
    select.title = `${t(label)}: ${select.selectedOptions[0].textContent}`;
    return select;
  }

  function row(command, index, length) {
    const value = decodeBasicSkill(command);
    const item = document.createElement("div");
    item.className = "turn-skill-row";
    item.classList.toggle("turn-skill-exchange", Boolean(value.swap));
    item.dataset.turnSkillIndex = String(index);
    item.setAttribute("role", "group");
    item.setAttribute("aria-label", t("Skill {index}", { index: index + 1 }));
    const skill = document.createElement("select");
    skill.className = "field";
    skill.dataset.turnSkillPart = "skill";
    skill.setAttribute("aria-label", t("Skill {index}", { index: index + 1 }));
    for (let number = 1; number <= 13; number += 1) {
      const label = number <= 9
        ? t("Servant {slot} / Skill {skill}", { slot: Math.floor((number - 1) / 3) + 1, skill: (number - 1) % 3 + 1 })
        : number <= 12 ? t("Master / Skill {skill}", { skill: number - 9 }) : t("Enemy target");
      skill.append(option(String(number), label));
    }
    for (let number = 10; number <= 12; number += 1) {
      skill.append(option(`swap:${number}`, t("Order change / Skill {skill}", { skill: number - 9 })));
    }
    skill.value = value.swap ? `swap:${value.skill}` : String(value.skill);
    skill.title = skill.selectedOptions[0].textContent;
    let target;
    if (value.swap) {
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
        field.append(heading, positionSelect(part, label, slots, position));
        target.append(field);
      }
    } else {
      target = document.createElement("select");
      target.className = "field";
      target.dataset.turnSkillPart = "target";
      const enemy = value.skill === 13;
      target.setAttribute("aria-label", t(enemy ? "Enemy target" : "Skill target"));
      if (!enemy) target.append(option("", t("No target")));
      for (let slot = 1; slot <= (enemy ? 6 : 3); slot += 1) {
        target.append(option(String(slot), t(enemy ? "Enemy {slot}" : "Servant {slot}", { slot })));
      }
      target.value = value.target === null ? "" : String(value.target);
      target.title = target.selectedOptions[0].textContent;
    }
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
    item.append(skill, target, tools);
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
        validateConfig(JSON.parse(source.value));
        const info = inspectSkillSource(source.value, target);
        list.replaceChildren(...(info.commands || []).map((command, index) => row(command, index, info.commands.length)));
        rendered = { editor, source: source.value, target, info };
      }
      controls.disabled = Boolean(editor.saving || editor.strategyApplyBusy);
      add.disabled = rendered.info.commands === null || rendered.info.commands.length >= MAX_SKILL_COMMANDS;
      clear.disabled = !rendered.info.canClear;
      count.textContent = rendered.info.commands === null ? "" : String(rendered.info.commands.length);
      status.textContent = rendered.info.error ? t(rendered.info.error) : "";
      status.hidden = !status.textContent;
    } catch (error) {
      rendered = null;
      controls.disabled = true;
      add.disabled = clear.disabled = true;
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
      source.value = changeSkillSource(source.value, field, change);
      onChange();
      if (getEditor() !== editor) return;
      const item = list.querySelector(`[data-turn-skill-index="${Math.max(focusIndex, 0)}"]`)
        || list.lastElementChild;
      const focus = item?.querySelector(`[data-turn-skill-part="${part}"]`) || add;
      focus.focus({ preventScroll: true });
    } catch (error) {
      onError(t(error.message));
    }
  }

  add.addEventListener("click", () => {
    if (!add.disabled) edit({ type: "add" }, rendered?.info.commands?.length || 0);
  });
  clear.addEventListener("click", () => {
    if (!clear.disabled && !controls.disabled && window.confirm(t("Clear the selected skill sequence?"))) edit({ type: "clear" });
  });
  list.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-turn-skill-part]");
    const item = select?.closest("[data-turn-skill-index]");
    if (!item) return;
    const index = Number(item.dataset.turnSkillIndex);
    const selection = item.querySelector('[data-turn-skill-part="skill"]').value;
    const exchange = selection.startsWith("swap:");
    const skill = Number(exchange ? selection.slice(5) : selection);
    const previous = decodeBasicSkill(rendered?.info.commands?.[index]);
    if (exchange) {
      const swap = select.dataset.turnSkillPart === "skill" ? previous?.swap || [1, 4]
        : [Number(item.querySelector('[data-turn-skill-part="front"]').value),
          Number(item.querySelector('[data-turn-skill-part="reserve"]').value)];
      edit({ type: "update", index, skill, swap }, index, select.dataset.turnSkillPart);
      return;
    }
    const selectedTarget = item.querySelector('[data-turn-skill-part="target"]')?.value || "";
    let target = selectedTarget === "" ? null : Number(selectedTarget);
    if (select.dataset.turnSkillPart === "skill" && previous
        && (previous.swap || (previous.skill === 13) !== (skill === 13))) {
      target = skill === 13 ? 1 : null;
    }
    edit({ type: "update", index, skill, target }, index, select.dataset.turnSkillPart);
  });
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-turn-skill-action]");
    if (!button || button.disabled) return;
    const index = Number(button.closest("[data-turn-skill-index]").dataset.turnSkillIndex);
    const action = button.dataset.turnSkillAction;
    if (action === "remove") edit({ type: "remove", index }, index);
    else edit({ type: "move", index, to: index + (action === "up" ? -1 : 1) }, index + (action === "up" ? -1 : 1));
  });
  return { render };
}
