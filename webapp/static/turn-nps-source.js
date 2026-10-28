import { readJsonField } from "./json-source.js";

function npField(target) {
  const match = typeof target === "string" ? /^round(0|[1-9][0-9]*)_turn(0|[1-9][0-9]*)_strategy$/.exec(target) : null;
  if (!match || !Number.isSafeInteger(Number(match[1])) || !Number.isSafeInteger(Number(match[2]))) {
    throw new Error("Select a valid script turn.");
  }
  return target.replace(/_strategy$/, "_np");
}

function sequence(source, entry) {
  const nps = entry.value === undefined ? [] : entry.value;
  if (!Array.isArray(nps) || nps.length > 3 || new Set(nps).size !== nps.length
      || nps.some((value) => !Number.isInteger(value) || value < 1 || value > 3)
      || entry.node?.children?.some((node) => !/^-?(?:0|[1-9][0-9]*)$/.test(source.slice(node.offset, node.offset + node.length)))) {
    throw new Error("Invalid NP sequence.");
  }
  return [...nps];
}

export function inspectNpSource(source, target) {
  const entry = readJsonField(source, npField(target), "Ambiguous NP field.");
  let nps = null;
  let error = null;
  try {
    nps = sequence(source, entry);
  } catch (failure) {
    error = failure.message;
  }
  return {
    field: entry.field, nps, error,
    canClear: Boolean(entry.node) && !(Array.isArray(entry.value) && entry.value.length === 0),
  };
}

export function changeNpSource(source, target, edit) {
  const entry = readJsonField(source, npField(target), "Ambiguous NP field.");
  if (edit?.type === "clear") return entry.replace([]);
  if (edit?.type !== "select") throw new Error("Invalid NP edit.");
  const nps = sequence(source, entry);
  const { index, servant } = edit;
  if (!Number.isInteger(index) || index < 0 || index > 2 || index > nps.length
      || !Number.isInteger(servant) || servant < 0 || servant > 3) {
    throw new Error("Invalid NP edit.");
  }
  if (servant === 0) {
    nps.splice(index, 1);
  } else {
    const previous = nps.indexOf(servant);
    if (previous !== -1) nps[previous] = nps[index];
    nps[index] = servant;
  }
  return entry.replace(nps.filter((value) => value !== undefined));
}
