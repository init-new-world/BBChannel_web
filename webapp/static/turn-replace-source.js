import { readJsonField } from "./json-source.js";

const SLOTS = ["1", "2", "3", "4", "5", "6"];

function replaceField(target) {
  const match = typeof target === "string" ? /^round(0|[1-9][0-9]*)_turn(0|[1-9][0-9]*)_strategy$/.exec(target) : null;
  if (!match || !Number.isSafeInteger(Number(match[1])) || !Number.isSafeInteger(Number(match[2]))) {
    throw new Error("Select a valid script turn.");
  }
  return target.replace(/_strategy$/, "_replace");
}

function replacements(source, entry) {
  const value = entry.value === undefined ? {} : entry.value;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid replacement mapping.");
  }
  const properties = entry.node?.children || [];
  const keys = properties.map((prop) => prop.children[0].value);
  if (new Set(keys).size !== keys.length) {
    throw new Error("Invalid replacement mapping.");
  }
  for (const prop of properties) {
    const slot = prop.children[0].value;
    const valNode = prop.children[1];
    const raw = source.slice(valNode.offset, valNode.offset + valNode.length);
    const val = value[slot];
    const validVal = (val === null && raw === "null")
      || (Number.isInteger(val) && val >= 1 && val <= 6 && /^[1-6]$/.test(raw));
    if (!SLOTS.includes(slot) || !validVal) {
      throw new Error("Invalid replacement mapping.");
    }
  }
  const ordered = {};
  for (const slot of SLOTS) {
    if (Object.hasOwn(value, slot)) ordered[slot] = value[slot];
  }
  return ordered;
}

export function inspectReplaceSource(source, target) {
  const entry = readJsonField(source, replaceField(target), "Ambiguous replacement field.");
  let map = null;
  let error = null;
  try {
    map = replacements(source, entry);
  } catch (failure) {
    error = failure.message;
  }
  return {
    field: entry.field,
    replacements: map,
    error,
    canClear: Boolean(entry.node) && !(map && Object.keys(map).length === 0),
  };
}

export function changeReplaceSource(source, target, edit) {
  const entry = readJsonField(source, replaceField(target), "Ambiguous replacement field.");
  if (edit?.type === "clear") return entry.replace({});
  if (edit?.type !== "set") throw new Error("Invalid replacement edit.");
  const map = replacements(source, entry);
  const slot = typeof edit.slot === "number" && Number.isInteger(edit.slot) ? String(edit.slot) : edit.slot;
  if (!SLOTS.includes(slot)) throw new Error("Invalid replacement edit.");
  const { sourceSlot } = edit;
  if (sourceSlot === undefined || sourceSlot === "") {
    delete map[slot];
  } else if (sourceSlot === null || sourceSlot === 0) {
    map[slot] = null;
  } else if (Number.isInteger(sourceSlot) && sourceSlot >= 1 && sourceSlot <= 6) {
    map[slot] = sourceSlot;
  } else {
    throw new Error("Invalid replacement edit.");
  }
  const ordered = {};
  for (const key of SLOTS) {
    if (Object.hasOwn(map, key)) ordered[key] = map[key];
  }
  return entry.replace(ordered);
}
