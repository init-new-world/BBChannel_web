import { t } from "./i18n.js";

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
    try {
      config = readConfig();
    } catch {
      controls.disabled = true;
      return;
    }
    inputs.forEach((input) => {
      const value = config[input.dataset.settlementOption];
      if (input.type === "checkbox") {
        input.checked = value && typeof value === "object" ? Object.keys(value).length > 0 : Boolean(value);
      } else {
        input.value = value === undefined ? "" : typeof value === "string" ? value : JSON.stringify(value);
        input.title = value !== undefined && typeof value !== "string"
          ? t("{name} (current)", { name: input.value }) : "";
      }
    });
  }

  inputs.forEach((input) => input.addEventListener(input.type === "checkbox" ? "change" : "input", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled) return;
    try {
      const config = readConfig();
      config[input.dataset.settlementOption] = input.type === "checkbox" ? input.checked : input.value;
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
    }
  }));
  return { render };
}
