import { parseJsonSource, readJsonField } from "./json-source.js";

const SCALAR_FIELDS = new Set(["server", "master_equip", "master_sex", "assistIdx"]);
const REMOVABLE_FIELDS = new Set(["server", "master_equip", "assistIdx"]);

function scalarField(field) {
  return SCALAR_FIELDS.has(field) || /^servant_[0-5]_name$/.test(field);
}

function validValue(field, value) {
  if (field === "server") return ["CH", "CNTW", "JP"].includes(value);
  if (field === "master_equip") return (typeof value === "string" && value !== "") || Number.isSafeInteger(value);
  if (field === "master_sex") return value === 0 || value === 1;
  if (field === "assistIdx") return Number.isInteger(value) && value >= 0 && value <= 5;
  return typeof value === "string";
}

function recognizedSlot(source, node) {
  return node.type === "number" && Number.isInteger(node.value) && node.value >= 0 && node.value <= 5
    && /^-?(?:0|[1-9][0-9]*)$/.test(source.slice(node.offset, node.offset + node.length));
}

function usedState(source, node) {
  if (!node) return { valid: true, slots: [0, 1, 2], unrecognized: false };
  if (node.type !== "array") return { valid: false, slots: [], unrecognized: false };
  const recognized = node.children.filter((child) => recognizedSlot(source, child));
  return {
    valid: true,
    slots: [...new Set(recognized.map((child) => child.value))],
    unrecognized: recognized.length !== node.children.length,
  };
}

export function inspectTeamSource(source) {
  const root = parseJsonSource(source);
  if (root.type !== "object") throw new Error("Invalid script JSON.");
  const fields = new Map();
  for (const property of root.children) {
    const name = property.children[0].value;
    if (!fields.has(name)) fields.set(name, []);
    fields.get(name).push(property.children[1]);
  }
  const ambiguous = [...fields].filter(([name, nodes]) => nodes.length > 1 && (scalarField(name) || name === "usedServant"))
    .map(([name]) => name);
  return {
    ambiguous,
    used: ambiguous.includes("usedServant") ? { valid: false, slots: [], unrecognized: false }
      : usedState(source, fields.get("usedServant")?.[0]),
  };
}

export function editTeamSource(source, edit) {
  if (!edit || !scalarField(edit.field) || !["set", "remove"].includes(edit.type)
      || (edit.type === "remove" ? !REMOVABLE_FIELDS.has(edit.field) : !validValue(edit.field, edit.value))) {
    throw new Error("Invalid team edit.");
  }
  const entry = readJsonField(source, edit.field, "Ambiguous team field.");
  return edit.type === "remove" ? entry.remove() : entry.replace(edit.value);
}

export function editUsedServantsSource(source, slot, checked) {
  if (!Number.isInteger(slot) || slot < 0 || slot > 5 || typeof checked !== "boolean") {
    throw new Error("Invalid team edit.");
  }
  const entry = readJsonField(source, "usedServant", "Ambiguous team field.");
  if (!entry.node) {
    const next = [0, 1, 2].filter((value) => value !== slot);
    if (checked) next.push(slot);
    return entry.replace(next);
  }
  if (entry.node.type !== "array") throw new Error("Invalid usedServant value.");
  const retained = entry.node.children.filter((node) => !recognizedSlot(source, node) || node.value !== slot)
    .map((node) => source.slice(node.offset, node.offset + node.length));
  if (checked) retained.push(String(slot));
  return entry.replaceSource(`[${retained.join(",")}]`);
}
