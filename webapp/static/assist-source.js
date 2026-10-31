import { parseJsonSource, readJsonField } from "./json-source.js";

const MODES = new Set(["\u4ece\u8005\u793c\u88c5", "\u4ec5\u4ece\u8005", "\u4ec5\u793c\u88c5", "\u4e0d\u8bc6\u522b", "\u51a0\u4f4d\u52a9\u6218", "\u51a0\u4f4d\u52a9\u6218\u4ec5\u793c\u88c5"]);
const BOND_TYPES = new Set(["\u4efb\u610f", "\u521d\u59cb", "NP50"]);
const FLAGS = new Set(["onlyFriendAssist", "allNotSkip", "fullEquip", "noGrandRefresh"]);
const NUMBERS = {
  NPlevel: [1, 5, true],
  servantLevel: [1, 120, true],
  intervalAFswipeAssist: [0, 10, false],
  scrollLimit: [0, 1, false],
};

function ownedField(field) {
  return typeof field === "string" && (field === "assistMode" || field === "jbType" || FLAGS.has(field) || Object.hasOwn(NUMBERS, field));
}

function validValue(field, value) {
  if (!ownedField(field)) return false;
  if (field === "assistMode") return MODES.has(value);
  if (field === "jbType") return BOND_TYPES.has(value);
  if (FLAGS.has(field)) return typeof value === "boolean";
  const [min, max, integer] = NUMBERS[field];
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isInteger(value));
}

export function inspectAssistSource(source) {
  const root = parseJsonSource(source);
  if (root.type !== "object") throw new Error("Invalid script JSON.");
  const counts = new Map();
  for (const property of root.children) {
    const field = property.children[0].value;
    if (ownedField(field)) counts.set(field, (counts.get(field) || 0) + 1);
  }
  return { ambiguous: [...counts].filter(([_field, count]) => count > 1).map(([field]) => field) };
}

export function editAssistSource(source, edit) {
  if (!edit || edit.type !== "set" || !validValue(edit.field, edit.value)) throw new Error("Invalid assist edit.");
  return readJsonField(source, edit.field, "Ambiguous assist field.").replace(edit.value);
}
