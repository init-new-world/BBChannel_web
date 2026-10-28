import { parseJsonSource, readJsonField } from "./json-source.js";

function document(source, target) {
  const match = typeof target === "string"
    ? /^round(0|[1-9][0-9]*)_(?:turn(0|[1-9][0-9]*)_strategy|extraStrategy)$/.exec(target) : null;
  if (!match || !Number.isSafeInteger(Number(match[1]))
      || (match[2] !== undefined && !Number.isSafeInteger(Number(match[2])))) {
    throw new Error("Select a valid script turn.");
  }
  return readJsonField(source, target, "Ambiguous strategy field.");
}

function presetSource(preset) {
  const invalid = () => new Error("Selected strategy preset is invalid or empty.");
  const record = (value) => value && typeof value === "object" && !Array.isArray(value);
  if (preset?.validation?.ok !== true || !Array.isArray(preset.entries) || !preset.entries.length
      || preset.entries.some((entry) => !record(entry) || !record(entry.strategy))) throw invalid();
  if (preset.source == null) return JSON.stringify(preset.entries.map((entry) => entry.strategy));
  if (typeof preset.source !== "string") throw invalid();
  let root;
  try {
    root = parseJsonSource(preset.source);
  } catch {
    throw invalid();
  }
  if (root.type !== "array" || root.children.length !== preset.entries.length) throw invalid();
  const values = root.children.map((entry) => {
    if (entry.type !== "object") throw invalid();
    const properties = entry.children.filter((property) => property.children[0].value === "strategy");
    if (properties.length !== 1 || properties[0].children[1].type !== "object") throw invalid();
    const node = properties[0].children[1];
    return preset.source.slice(node.offset, node.offset + node.length);
  });
  return `[${values.join(",")}]`;
}

export function inspectStrategySource(source, target) {
  const entry = document(source, target);
  return {
    field: entry.field,
    canClear: entry.value != null && (!Array.isArray(entry.value) || entry.value.length > 0),
  };
}

export function applyStrategySource(source, target, preset) {
  const entry = document(source, target);
  return entry.replaceSource(presetSource(preset));
}

export function clearStrategySource(source, target) {
  return document(source, target).replace([]);
}
