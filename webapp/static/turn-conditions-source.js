import { parseJsonSource, readJsonField } from "./json-source.js";
import { skillField } from "./turn-skills-model.js";
import {
  changeMixedSkillSequence,
  conditionField,
  isValidConditionStrategyPayload,
  readMixedSkillEntries,
} from "./turn-conditions-model.js";

function assertCanonicalIntegers(source, node, errorMessage) {
  if (!node) return;
  if (node.type === "number") {
    const token = source.slice(node.offset, node.offset + node.length);
    if (!/^-?(?:0|[1-9][0-9]*)$/.test(token)) {
      throw new Error(errorMessage);
    }
    return;
  }
  for (const child of node.children || []) {
    assertCanonicalIntegers(source, child, errorMessage);
  }
}

export function inspectMixedSkillSource(source, strategyField) {
  const entry = readJsonField(source, skillField(strategyField), "Ambiguous skill field.");
  let commands = null;
  let error = null;
  try {
    const parsed = readMixedSkillEntries(entry.value);
    assertCanonicalIntegers(source, entry.node, "Advanced skill sequence.");
    commands = parsed;
  } catch (failure) {
    error = failure.message;
  }
  return {
    field: entry.field,
    commands,
    error,
    canClear: Boolean(entry.node) && !(Array.isArray(entry.value) && entry.value.length === 0),
  };
}

export function changeMixedSkillSource(source, strategyField, edit) {
  const entry = readJsonField(source, skillField(strategyField), "Ambiguous skill field.");
  let value = entry.value;
  if (edit?.type !== "clear") {
    value = readMixedSkillEntries(entry.value);
    assertCanonicalIntegers(source, entry.node, "Advanced skill sequence.");
  }
  const next = changeMixedSkillSequence(value, edit);
  return entry.replace(next);
}

function presetStrategyItems(preset) {
  const invalid = () => new Error("Selected strategy preset is invalid or empty.");
  const record = (value) => value && typeof value === "object" && !Array.isArray(value);
  if (
    preset?.validation?.ok !== true
    || !Array.isArray(preset.entries)
    || !preset.entries.length
    || preset.entries.some((item) => !record(item) || !record(item.strategy))
  ) {
    throw invalid();
  }
  if (preset.source == null) {
    return preset.entries.map((item) => JSON.stringify(item.strategy));
  }
  if (typeof preset.source !== "string") throw invalid();
  let root;
  try {
    root = parseJsonSource(preset.source);
  } catch {
    throw invalid();
  }
  if (root.type !== "array" || root.children.length !== preset.entries.length) throw invalid();
  return root.children.map((item) => {
    if (item.type !== "object") throw invalid();
    const properties = item.children.filter((property) => property.children[0].value === "strategy");
    if (properties.length !== 1 || properties[0].children[1].type !== "object") throw invalid();
    const node = properties[0].children[1];
    return preset.source.slice(node.offset, node.offset + node.length);
  });
}

function readConditionEntry(source, target) {
  const entry = readJsonField(source, conditionField(target), "Ambiguous condition field.");
  return entry;
}

export function inspectConditionSource(source, target) {
  const entry = readConditionEntry(source, target);
  if (entry.value === undefined) {
    return { field: entry.field, entries: [], error: null, canClear: false };
  }
  if (!Array.isArray(entry.value) || entry.value.some((item) => !isValidConditionStrategyPayload(item))) {
    return {
      field: entry.field,
      entries: null,
      error: "Invalid condition strategy.",
      canClear: Boolean(entry.node),
    };
  }
  return {
    field: entry.field,
    entries: entry.value,
    error: null,
    canClear: entry.value.length > 0,
  };
}

export function changeConditionSource(source, target, edit) {
  if (!edit || typeof edit !== "object") throw new Error("Invalid condition edit.");
  const entry = readConditionEntry(source, target);
  if (edit.type === "clear") {
    return entry.remove();
  }
  const existingNodes = entry.node
    ? (entry.node.type === "array"
        ? entry.node.children.map((child) => source.slice(child.offset, child.offset + child.length))
        : (() => { throw new Error("Invalid condition strategy."); })())
    : [];
  const current = entry.value === undefined ? [] : entry.value;
  if (!Array.isArray(current) || current.some((item) => !isValidConditionStrategyPayload(item))) {
    throw new Error("Invalid condition strategy.");
  }
  let nextItems;
  if (edit.type === "append-preset") {
    const added = presetStrategyItems(edit.preset);
    nextItems = [...existingNodes, ...added];
  } else if (edit.type === "remove") {
    if (!Number.isInteger(edit.index) || edit.index < 0 || edit.index >= existingNodes.length) {
      throw new Error("Select a valid condition entry.");
    }
    nextItems = existingNodes.slice();
    nextItems.splice(edit.index, 1);
    if (!nextItems.length) {
      return entry.remove();
    }
  } else if (edit.type === "move") {
    const from = edit.index;
    const to = edit.to;
    if (
      !Number.isInteger(from)
      || !Number.isInteger(to)
      || from < 0
      || from >= existingNodes.length
      || to < 0
      || to >= existingNodes.length
    ) {
      throw new Error("Select a valid condition entry.");
    }
    nextItems = existingNodes.slice();
    nextItems.splice(to, 0, nextItems.splice(from, 1)[0]);
  } else {
    throw new Error("Invalid condition edit.");
  }
  return entry.replaceSource(`[${nextItems.join(",")}]`);
}
