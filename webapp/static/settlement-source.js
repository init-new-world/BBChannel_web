import { parseJsonSource, readJsonField } from "./json-source.js";

const FLAGS = new Set(["fullFriendshipStop", "addFriend"]);

function ownedField(field) {
  return field === "ignoreFriendship" || FLAGS.has(field);
}

export function inspectSettlementSource(source) {
  const root = parseJsonSource(source);
  if (root.type !== "object") throw new Error("Invalid script JSON.");
  const counts = new Map();
  for (const property of root.children) {
    const field = property.children[0].value;
    if (ownedField(field)) counts.set(field, (counts.get(field) || 0) + 1);
  }
  return { ambiguous: [...counts].filter(([_field, count]) => count > 1).map(([field]) => field) };
}

export function editSettlementSource(source, edit) {
  if (!edit || edit.type !== "set" || !ownedField(edit.field)
      || typeof edit.value !== (FLAGS.has(edit.field) ? "boolean" : "string")) {
    throw new Error("Invalid settlement edit.");
  }
  return readJsonField(source, edit.field, "Ambiguous settlement field.").replace(edit.value);
}
