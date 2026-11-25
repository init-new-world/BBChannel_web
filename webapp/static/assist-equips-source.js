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

const GRAND_MODES = new Set(["\u51a0\u4f4d\u52a9\u6218", "\u51a0\u4f4d\u52a9\u6218\u4ec5\u793c\u88c5"]);
const GRAND_SLOT_LABELS = ["normal", "kizuna", "houshuu"];

function isGrandAssistMode(source) {
  try {
    const modeEntry = readJsonField(source, "assistMode", "Ambiguous assist field.");
    return typeof modeEntry.value === "string" && GRAND_MODES.has(modeEntry.value);
  } catch {
    return false;
  }
}

function isGrandSlotArray(value) {
  return Array.isArray(value) && value.length === 3 && value.some((item) => item === null || Array.isArray(item));
}

function collectGrandSlots(value) {
  if (!isGrandSlotArray(value)) return null;
  const slotsByName = {};
  value.forEach((slotValue, slotIndex) => {
    const slotKey = GRAND_SLOT_LABELS[slotIndex];
    if (!slotKey || slotValue == null) return;
    const slotNames = readAssistEquipNames(slotValue);
    for (const name of slotNames) {
      if (!slotsByName[name]) slotsByName[name] = [];
      if (!slotsByName[name].includes(slotKey)) slotsByName[name].push(slotKey);
    }
  });
  return slotsByName;
}

export function inspectAssistEquipGrandSlots(source) {
  try {
    if (!isGrandAssistMode(source)) return null;
    const entry = document(source);
    return collectGrandSlots(entry.value);
  } catch {
    return null;
  }
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

function removeNameGrand(slots, name) {
  return slots.map((slot) => {
    if (slot === name) return null;
    if (Array.isArray(slot)) return removeName(slot, name);
    return slot;
  });
}

function addNameGrand(slots, name, slotIndex = 0) {
  const targetIdx = Number.isInteger(slotIndex) && slotIndex >= 0 && slotIndex < 3 ? slotIndex : 0;
  return slots.map((slot, idx) => {
    if (idx !== targetIdx) return slot;
    if (slot == null || slot === "") return [name];
    if (typeof slot === "string") return [slot, name];
    if (Array.isArray(slot)) return [...slot, name];
    return [name];
  });
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
  const grandStructured = isGrandAssistMode(source) && isGrandSlotArray(entry.value);
  if (edit.type === "remove") {
    if (!names.includes(edit.name)) return source;
    const next = grandStructured ? removeNameGrand(entry.value, edit.name) : removeName(entry.value, edit.name);
    return entry.replace(next);
  }
  if (names.includes(edit.name)) return source;
  const current = entry.value;
  const next = grandStructured
    ? addNameGrand(current, edit.name, edit.slot)
    : Array.isArray(current) ? [...current, edit.name] : current ? [current, edit.name] : [edit.name];
  readAssistEquipNames(next);
  return entry.replace(next);
}
