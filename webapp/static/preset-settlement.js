import { t } from "./i18n.js";
import { editSettlementSource, inspectSettlementSource } from "./settlement-source.js";

export function createPresetSettlementEditor({ getEditor, source, onChange, onError }) {
  const section = document.querySelector("#preset-settlement");
  const controls = document.querySelector("#preset-settlement-controls");
  const inputs = [...document.querySelectorAll("[data-settlement-option]")];

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error(t("Invalid script JSON."));
    return config;
  }

  function render() {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") return;
    if (!editor.settlementInitialized) {
      section.open = false;
      editor.settlementInitialized = true;
    }
    let config;
    let ambiguous;
    try {
      config = readConfig();
      ambiguous = new Set(inspectSettlementSource(source.value).ambiguous);
    } catch {
      controls.disabled = true;
      return;
    }
    inputs.forEach((input) => {
      const field = input.dataset.settlementOption;
      const value = config[field];
      input.disabled = ambiguous.has(field);
      if (input.type === "checkbox") {
        input.checked = value && typeof value === "object" ? Object.keys(value).length > 0 : Boolean(value);
        input.removeAttribute("title");
      } else {
        input.value = value === undefined ? "" : typeof value === "string" ? value : JSON.stringify(value);
        input.title = value !== undefined && typeof value !== "string"
          ? t("{name} (current)", { name: input.value }) : "";
      }
      if (input.disabled) input.title = t("Ambiguous settlement field.");
    });
  }

  inputs.forEach((input) => input.addEventListener(input.type === "checkbox" ? "change" : "input", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled || input.disabled) return;
    try {
      source.value = editSettlementSource(source.value, {
        type: "set", field: input.dataset.settlementOption,
        value: input.type === "checkbox" ? input.checked : input.value,
      });
      onChange();
    } catch (error) {
      onError(t(error.message));
    }
  }));
  return { render };
}
