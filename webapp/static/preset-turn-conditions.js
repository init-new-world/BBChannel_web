import { t } from "./i18n.js";
import { changeConditionSource, inspectConditionSource } from "./turn-conditions-source.js";

const CARD_TYPE_LABELS = {
  0: "Fixed card",
  1: "Specific cards",
  2: "NP card",
};

function describeCard(card) {
  const label = t(CARD_TYPE_LABELS[card?.type] || String(card?.type ?? ""));
  const cards = Array.isArray(card?.cards) && card.cards.length ? card.cards.join("/") : "-";
  const star = card?.criticalStar ? ` · ${card.more_or_less ? "≥" : "≤"}${card.criticalStar}★` : "";
  return `${label}(${cards}${star})`;
}

export function describeConditionEntry(entry, index) {
  const parts = [
    describeCard(entry.card1),
    describeCard(entry.card2),
    describeCard(entry.card3),
  ];
  const flags = [];
  if (entry.colorFirst) flags.push(t("Color chain first"));
  if (Array.isArray(entry.breakpoint) && entry.breakpoint.some(Boolean)) {
    flags.push(t("Breakpoints"));
  }
  return `#${index + 1}: ${parts.join(" → ")}${flags.length ? ` (${flags.join(", ")})` : ""}`;
}

export function createPresetTurnConditionsEditor({
  getEditor,
  source,
  readTarget,
  getSelectedPreset,
  loadPreset,
  validateConfig,
  onChange,
  onError,
}) {
  const section = document.querySelector("#preset-turn-conditions");
  const controls = document.querySelector("#preset-turn-condition-controls");
  const list = document.querySelector("#preset-turn-condition-list");
  const status = document.querySelector("#preset-turn-condition-status");
  const count = document.querySelector("#preset-turn-condition-count");
  const addPreset = document.querySelector("#add-turn-condition-preset");
  const clear = document.querySelector("#clear-turn-conditions");
  let rendered = null;

  function render(target) {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    if (editor?.kind === "settings" && !editor.turnConditionsInitialized) {
      section.open = false;
      editor.turnConditionsInitialized = true;
    }
    try {
      if (editor?.kind !== "settings" || !target) throw new Error("No turn selected");
      const config = JSON.parse(source.value);
      validateConfig(config);
      const info = inspectConditionSource(source.value, target);
      if (rendered?.editor !== editor || rendered.source !== source.value || rendered.target !== target) {
        const items = (info.entries || []).map((entry, index) => {
          const row = document.createElement("div");
          row.className = "turn-condition-row";
          row.dataset.turnConditionIndex = String(index);

          const label = document.createElement("span");
          label.className = "turn-condition-summary";
          label.textContent = describeConditionEntry(entry, index);

          const tools = document.createElement("div");
          tools.className = "turn-skill-tools";
          for (const [action, icon, text, disabled] of [
            ["up", "arrow-up", "Move condition up", index === 0],
            ["down", "arrow-down", "Move condition down", index === info.entries.length - 1],
            ["remove", "trash-2", "Remove condition", false],
          ]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "icon-button";
            button.dataset.turnConditionAction = action;
            button.title = t(text);
            button.setAttribute("aria-label", t(text));
            button.disabled = disabled;
            const img = document.createElement("img");
            img.src = `/icons/${icon}.svg`;
            img.width = img.height = 16;
            img.alt = "";
            button.append(img);
            tools.append(button);
          }

          row.append(label, tools);
          return row;
        });
        list.replaceChildren(...items);
        rendered = { editor, source: source.value, target, info };
      }
      const busy = Boolean(editor.saving || editor.strategyApplyBusy);
      controls.disabled = busy;
      const preset = getSelectedPreset();
      addPreset.disabled = busy || info.entries === null || !preset;
      clear.disabled = busy || !info.canClear;
      count.textContent = info.entries === null ? "" : String(info.entries.length);
      status.textContent = info.error ? t(info.error) : "";
      status.hidden = !status.textContent;
    } catch (error) {
      rendered = null;
      controls.disabled = true;
      addPreset.disabled = clear.disabled = true;
      list.replaceChildren();
      count.textContent = "";
      status.textContent = t(error.message);
      status.hidden = false;
    }
  }

  function applyEdit(edit) {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled) return;
    try {
      const { config, field } = readTarget();
      validateConfig(config);
      source.value = changeConditionSource(source.value, field, edit);
      onChange();
    } catch (error) {
      onError(t(error.message));
    }
  }

  addPreset.addEventListener("click", async () => {
    if (addPreset.disabled) return;
    const presetName = getSelectedPreset();
    if (!presetName) return;
    const editor = getEditor();
    try {
      const { config, field } = readTarget();
      validateConfig(config);
      const sourceJson = source.value;
      addPreset.disabled = true;
      const preset = await loadPreset(presetName);
      if (getEditor() !== editor || !preset) return;
      if (source.value !== sourceJson) {
        throw new Error("Script changed while the preset was loading. Apply it again.");
      }
      if (readTarget().field !== field) {
        throw new Error("Script turn changed while the preset was loading. Apply it again.");
      }
      source.value = changeConditionSource(sourceJson, field, { type: "append-preset", preset });
      onChange();
    } catch (error) {
      if (getEditor() === editor) onError(t(error.message));
    } finally {
      if (getEditor() === editor) {
        let currentTarget = "";
        try { currentTarget = readTarget()?.field || ""; } catch {}
        render(currentTarget);
      }
    }
  });

  clear.addEventListener("click", () => {
    if (!clear.disabled && window.confirm(t("Clear condition strategies for this turn?"))) {
      applyEdit({ type: "clear" });
    }
  });

  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-turn-condition-action]");
    if (!button || button.disabled) return;
    const index = Number(button.closest("[data-turn-condition-index]").dataset.turnConditionIndex);
    const action = button.dataset.turnConditionAction;
    if (action === "remove") {
      applyEdit({ type: "remove", index });
    } else {
      applyEdit({ type: "move", index, to: index + (action === "up" ? -1 : 1) });
    }
  });

  return { render };
}
