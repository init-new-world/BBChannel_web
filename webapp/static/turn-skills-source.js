import { applyEdits, modify, parseTree } from "./vendor/jsonc-parser.js";
import { changeSkillSequence, readBasicSkills, skillField } from "./turn-skills-model.js";

function document(source, strategyField) {
  const field = skillField(strategyField);
  if (typeof source !== "string") throw new Error("Invalid script JSON.");
  const errors = [];
  let root;
  try {
    root = parseTree(source, errors, { disallowComments: true, allowTrailingComma: false, allowEmptyContent: false });
  } catch {
    throw new Error("Invalid script JSON.");
  }
  if (errors.length || root?.type !== "object") throw new Error("Invalid script JSON.");
  const properties = root.children.filter((property) => property.children[0].value === field);
  if (properties.length > 1) throw new Error("Ambiguous skill field.");
  const node = properties[0]?.children[1];
  const value = node ? JSON.parse(source.slice(node.offset, node.offset + node.length)) : undefined;
  return { field, node, value };
}

function basicCommands(source, entry) {
  const commands = readBasicSkills(entry.value);
  // JSON.parse erases integer/float spelling; check Python's integer tokens at AST offsets.
  for (const node of entry.node?.children || []) {
    for (const token of node.type === "array" ? node.children : [node]) {
      if (token.type === "number" && !/^-?(?:0|[1-9][0-9]*)$/.test(source.slice(token.offset, token.offset + token.length))) {
        throw new Error("Advanced skill sequence.");
      }
    }
  }
  return commands;
}

export function inspectSkillSource(source, strategyField) {
  const entry = document(source, strategyField);
  let commands = null;
  let error = null;
  try {
    commands = basicCommands(source, entry);
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

export function changeSkillSource(source, strategyField, edit) {
  const entry = document(source, strategyField);
  const value = edit?.type === "clear" ? entry.value : basicCommands(source, entry);
  const next = changeSkillSequence(value, edit);
  if (entry.node) {
    return applyEdits(source, [{ offset: entry.node.offset, length: entry.node.length, content: JSON.stringify(next) }]);
  }
  return applyEdits(source, modify(source, [entry.field], next, {
    formattingOptions: { insertSpaces: true, tabSize: 2, eol: source.includes("\r\n") ? "\r\n" : "\n" },
  }));
}
