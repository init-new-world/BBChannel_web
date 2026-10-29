import { t } from "./i18n.js";
import { changeHakunoNeeds, MAX_HAKUNO_COMBINATIONS } from "./hakuno-needs-model.js";

const ORDINARY_CARDS = [1, 2, 3].flatMap((slot) => ["B", "A", "Q"].map((color) => `${slot}${color}`));

export function createHakunoNeedsControls() {
  let currentEditor = null;
  let active = null;
  const groups = new Map();
  const key = (field, index) => `${field}:${index}`;

  function ensureEditor(editor) {
    if (currentEditor !== editor) {
      currentEditor = editor;
      active = null;
      groups.clear();
    }
  }

  function selected(context) {
    return Math.max(0, Math.min(groups.get(key(context.field, context.index)) || 0, context.needs.length - 1));
  }

  function button(action, icon, label, disabled = false, card) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "icon-button";
    node.dataset.hakunoNeedsAction = action;
    if (card !== undefined) node.dataset.hakunoCardIndex = String(card);
    if (action === "add") node.dataset.turnSkillPart = "needs-add";
    node.title = t(label);
    node.setAttribute("aria-label", t(label));
    node.disabled = disabled;
    const image = document.createElement("img");
    image.src = `/icons/${icon}.svg`;
    image.width = image.height = 16;
    image.alt = "";
    node.append(image);
    return node;
  }

  function option(value, label) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    return node;
  }

  function panel(context) {
    const { needs, config } = context;
    const group = selected(context);
    const cards = needs[group] || [];
    const body = document.createElement("div");
    body.className = "hakuno-needs-panel";
    const header = document.createElement("div");
    header.className = "hakuno-needs-heading";
    const select = document.createElement("select");
    select.className = "field";
    select.dataset.turnSkillPart = "needs-group";
    select.setAttribute("aria-label", t("Card combination"));
    if (!needs.length) select.append(option("", t("Cast Once")));
    needs.forEach((_cards, index) => select.append(option(String(index), t("Combination {index}", { index: index + 1 }))));
    select.value = needs.length ? String(group) : "";
    select.title = select.selectedOptions[0].textContent;
    select.disabled = !needs.length;
    header.append(select, button("add", "plus", "Add combination", needs.length >= MAX_HAKUNO_COMBINATIONS),
      button("remove", "trash-2", "Remove combination", !needs.length));
    const grid = document.createElement("div");
    grid.className = "hakuno-needs-cards";
    const codes = ORDINARY_CARDS.slice();
    const tagCount = Array.isArray(config.specialKeys) ? Math.min(config.specialKeys.length, 1000) : 0;
    for (let index = 0; index < tagCount; index += 1) {
      codes.push(`S${index}`, ...ORDINARY_CARDS.map((code) => `${code}S${index}`));
    }
    cards.forEach((code, index) => {
      const cell = document.createElement("div");
      cell.className = "hakuno-needs-card";
      const choice = document.createElement("select");
      choice.className = "field";
      choice.dataset.turnSkillPart = `needs-card-${index}`;
      choice.setAttribute("aria-label", t("Required card {index}", { index: index + 1 }));
      codes.forEach((value) => choice.append(option(value, value)));
      const missing = !codes.includes(code);
      if (missing) {
        const current = option(code, code);
        current.disabled = true;
        choice.append(current);
      }
      choice.value = code;
      choice.title = missing ? t("{name} (current)", { name: code }) : code;
      cell.append(choice, button("remove-card", "trash-2", "Remove required card", false, index));
      grid.append(cell);
    });
    const footer = document.createElement("div");
    footer.className = "hakuno-needs-actions";
    const count = document.createElement("span");
    count.textContent = `${cards.length}/5`;
    count.setAttribute("aria-label", t("Required card count"));
    footer.append(button("add-card", "plus", "Add required card", !needs.length || cards.length >= 5),
      button("up", "arrow-up", "Move combination up", !needs.length || group === 0),
      button("down", "arrow-down", "Move combination down", !needs.length || group === needs.length - 1), count);
    body.append(header, grid, footer);
    return body;
  }

  function render(context) {
    ensureEditor(context.editor);
    const id = key(context.field, context.index);
    const root = document.createElement("details");
    root.className = "turn-skill-named-controls turn-skill-hakuno-controls";
    const summary = document.createElement("summary");
    summary.textContent = `${t("Card Needs")} ${context.needs.length ? context.needs.length : t("Cast Once")}`;
    root.append(summary);
    root.open = active === id;
    if (root.open) root.append(panel(context));
    root.addEventListener("toggle", () => {
      if (!root.isConnected) return;
      if (root.open) {
        active = id;
        for (const other of root.closest(".turn-skill-list").querySelectorAll(".turn-skill-hakuno-controls")) {
          if (other !== root) {
            other.open = false;
            other.querySelector(".hakuno-needs-panel")?.remove();
          }
        }
        if (!root.querySelector(".hakuno-needs-panel")) root.append(panel(context));
      } else {
        if (active === id) active = null;
        root.querySelector(".hakuno-needs-panel")?.remove();
      }
    });
    return root;
  }

  function activate(field, index, editor) {
    ensureEditor(editor);
    active = key(field, index);
  }

  function select(context, group) {
    if (!Number.isInteger(group) || group < 0 || group >= context.needs.length) throw new Error("Select a valid Hakuno combination.");
    activate(context.field, context.index, context.editor);
    groups.set(active, group);
  }

  function change(context, edit) {
    const group = selected(context);
    const action = edit.action;
    const change = action === "up" || action === "down"
      ? { type: "move", index: group, to: group + (action === "up" ? -1 : 1) }
      : { type: action, index: group, card: edit.card, code: edit.code };
    const needs = changeHakunoNeeds(context.needs, change);
    let nextGroup = action === "add" ? needs.length - 1 : change.type === "move" ? change.to : Math.max(0, Math.min(group, needs.length - 1));
    let part = needs.length ? "needs-group" : "needs-add";
    if (action === "add-card") part = `needs-card-${context.needs[group].length}`;
    if (action === "update-card") part = `needs-card-${edit.card}`;
    if (action === "remove-card" && needs.length === context.needs.length) part = `needs-card-${Math.min(edit.card, needs[nextGroup].length - 1)}`;
    activate(context.field, context.index, context.editor);
    groups.set(active, nextGroup);
    return { needs, part };
  }

  function forget(field) {
    for (const id of groups.keys()) if (id.startsWith(`${field}:`)) groups.delete(id);
    if (active?.startsWith(`${field}:`)) active = null;
  }

  return { render, activate, select, change, forget };
}
