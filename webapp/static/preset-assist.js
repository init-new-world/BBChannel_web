import { t } from "./i18n.js";

export function createPresetAssistEditor({ getEditor, source, onChange, onError }) {
  const section = document.querySelector("#preset-assist-options");
  const controls = document.querySelector("#preset-assist-controls");
  const inputs = [...document.querySelectorAll("[data-assist-option]")];
  const mode = inputs.find((input) => input.dataset.assistOption === "assistMode");

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error(t("Invalid script JSON."));
    return config;
  }

  function optionValue(select, option) {
    return select.dataset.valueType === "number" ? Number(option.value) : option.value;
  }

  function runtimeFlag(value) {
    // Python treats empty JSON arrays and objects as false.
    return value && typeof value === "object" ? Object.keys(value).length > 0 : Boolean(value);
  }

  function renderSelect(select, value) {
    select.querySelector("option[data-current]")?.remove();
    const selected = value === undefined ? select.options[0]
      : [...select.options].find((option) => optionValue(select, option) === value);
    if (selected) {
      select.value = selected.value;
    } else {
      const current = document.createElement("option");
      current.value = "";
      current.textContent = t("{name} (current)", { name: JSON.stringify(value) });
      current.dataset.current = "";
      current.disabled = true;
      select.append(current);
      select.selectedIndex = select.options.length - 1;
    }
    select.title = select.selectedOptions[0]?.textContent || "";
  }

  function render() {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") return false;
    if (!editor.assistOptionsInitialized) {
      section.open = false;
      editor.assistOptionsInitialized = true;
    }
    let config;
    try {
      config = readConfig();
    } catch {
      controls.disabled = true;
      return false;
    }
    inputs.forEach((input) => {
      const value = config[input.dataset.assistOption];
      if (input.type === "checkbox") input.checked = runtimeFlag(value === undefined ? input.dataset.default === "true" : value);
      else renderSelect(input, value);
    });
    const effectiveMode = config.assistMode || mode.options[0].value;
    const modeOption = [...mode.options].find((option) => !option.hasAttribute("data-current") && option.value === effectiveMode);
    inputs.forEach((input) => {
      const requirement = input.dataset.assistRequires;
      input.disabled = Boolean(requirement) && !modeOption?.hasAttribute(`data-${requirement}`);
    });
    return Boolean(modeOption?.hasAttribute("data-equip"));
  }

  inputs.forEach((input) => input.addEventListener("change", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled || input.disabled) return;
    if (input.type !== "checkbox" && input.selectedOptions[0]?.disabled) return;
    try {
      const config = readConfig();
      config[input.dataset.assistOption] = input.type === "checkbox" ? input.checked : optionValue(input, input.selectedOptions[0]);
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
    }
  }));
  return { render };
}
