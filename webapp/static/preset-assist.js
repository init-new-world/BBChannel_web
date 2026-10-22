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

  function validNumber(input, value) {
    return typeof value === "number" && Number.isFinite(value)
      && value >= Number(input.min) && value <= Number(input.max)
      && (input.step !== "1" || Number.isInteger(value));
  }

  function renderNumber(input, config, editor) {
    const field = input.dataset.assistOption;
    const draft = editor.assistNumberDrafts?.[field];
    input.setCustomValidity(draft?.error ? t(draft.error) : "");
    // Preserve native partial numbers such as "1e" across unrelated renders.
    if (draft) return;
    const value = config[field] === undefined ? Number(input.dataset.default) : config[field];
    const valid = validNumber(input, value);
    input.value = valid ? String(value) : "";
    input.placeholder = valid ? "" : t("{name} (current)", { name: JSON.stringify(value) });
    input.title = input.placeholder;
  }

  function updateNumber(input, commit) {
    const editor = getEditor();
    if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || controls.disabled || input.disabled) return;
    try {
      const config = readConfig();
      const field = input.dataset.assistOption;
      const value = input.valueAsNumber;
      input.setCustomValidity("");
      editor.assistNumberDrafts ||= {};
      if (!validNumber(input, value) || !input.validity.valid) {
        editor.assistNumberDrafts[field] = { error: input.dataset.numberError };
        input.setCustomValidity(t(input.dataset.numberError));
        return;
      }
      if (commit) delete editor.assistNumberDrafts[field];
      else editor.assistNumberDrafts[field] = {};
      config[field] = value;
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
    }
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
      else if (input.type === "number") renderNumber(input, config, editor);
      else renderSelect(input, value);
    });
    const effectiveMode = config.assistMode || mode.options[0].value;
    const modeOption = [...mode.options].find((option) => !option.hasAttribute("data-current") && option.value === effectiveMode);
    inputs.forEach((input) => {
      const requirement = input.dataset.assistRequires;
      const editingDraft = editor.assistNumberDrafts?.[input.dataset.assistOption];
      input.disabled = Boolean(requirement) && !modeOption?.hasAttribute(`data-${requirement}`) && !editingDraft;
    });
    return Boolean(modeOption?.hasAttribute("data-equip"));
  }

  inputs.forEach((input) => input.addEventListener("change", () => {
    if (input.type === "number") return updateNumber(input, true);
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
  inputs.filter((input) => input.type === "number").forEach((input) => {
    input.addEventListener("input", () => updateNumber(input, false));
    input.addEventListener("blur", () => {
      if (getEditor()?.assistNumberDrafts?.[input.dataset.assistOption]) updateNumber(input, true);
    });
    input.addEventListener("invalid", () => { section.open = true; });
  });
  source.addEventListener("input", () => {
    const editor = getEditor();
    if (editor) editor.assistNumberDrafts = {};
  });

  function validate() {
    const editor = getEditor();
    const invalid = inputs.find((input) => editor?.assistNumberDrafts?.[input.dataset.assistOption]?.error);
    if (!invalid) return true;
    section.open = true;
    render();
    onError(t(editor.assistNumberDrafts[invalid.dataset.assistOption].error));
    invalid.reportValidity();
    return false;
  }

  return { render, validate };
}
