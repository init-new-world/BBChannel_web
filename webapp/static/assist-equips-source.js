import { readJsonField } from "./json-source.js";

export const MAX_ASSIST_EQUIP_VALUES = 1000;

export function readAssistEquipNames(value) {
  const names = new Set();
  const pending = [value];
  let visited = 0;
  while (pending.length) {
    if (++visited > MAX_ASSIST_EQUIP_VALUES) throw new Error("CE list exceeds 1,000 values.");
    const item = pending.pop();
    if (item == null) continue;
    if (typeof item === "string") {
      if (item) names.add(item);
    } else if (Array.isArray(item)) {
      if (visited + pending.length + item.length > MAX_ASSIST_EQUIP_VALUES) throw new Error("CE list exceeds 1,000 values.");
      for (let index = item.length - 1; index >= 0; index -= 1) pending.push(item[index]);
    } else {
      throw new Error("Unsupported CE value.");
    }
  }
  return [...names];
}

function document(source) {
  return readJsonField(source, "assistEquip", "Ambiguous CE field.");
}

export function inspectAssistEquipSource(source) {
  const entry = document(source);
  let names = null;
  let error = null;
  try {
    names = readAssistEquipNames(entry.value);
  } catch (failure) {
    error = failure.message;
  }
  return {
    names,
    error,
    canClear: Boolean(entry.node) && !(Array.isArray(entry.value) && !entry.value.length),
  };
}

function removeName(value, name) {
  if (!Array.isArray(value)) return value === name ? [] : value;
  return value.filter((item) => item !== name).map((item) => removeName(item, name));
}

export function editAssistEquipSource(source, edit) {
  if (!edit || !["add", "remove", "clear"].includes(edit.type)
      || (edit.type !== "clear" && (typeof edit.name !== "string" || !edit.name))) {
    throw new Error("Invalid CE edit.");
  }
  const entry = document(source);
  if (edit.type === "clear") {
    return !entry.node || (Array.isArray(entry.value) && !entry.value.length) ? source : entry.replace([]);
  }
  const names = readAssistEquipNames(entry.value);
  if (edit.type === "remove") {
    return names.includes(edit.name) ? entry.replace(removeName(entry.value, edit.name)) : source;
  }
  if (names.includes(edit.name)) return source;
  const current = entry.value;
  const next = Array.isArray(current) ? [...current, edit.name] : current ? [current, edit.name] : [edit.name];
  readAssistEquipNames(next);
  return entry.replace(next);
}
