import { readJsonField } from "./json-source.js";
import { changeSkillSequence, readBasicSkills, skillField } from "./turn-skills-model.js";

function document(source, strategyField) {
  return readJsonField(source, skillField(strategyField), "Ambiguous skill field.");
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
  return entry.replace(next);
}
