import { changeSkillSequence, decodeBasicSkill, MAX_SKILL_COMMANDS } from "./turn-skills-model.js";

export const DEFAULT_NP_CHECKS = Object.freeze([
  Object.freeze({ enabled: false, op: "≥", value: 100 }),
  Object.freeze({ enabled: false, op: "≥", value: 100 }),
  Object.freeze({ enabled: false, op: "≥", value: 100 }),
]);

export function conditionField(strategyField) {
  const match = typeof strategyField === "string"
    ? /^round(0|[1-9][0-9]*)_(?:turn(0|[1-9][0-9]*)_strategy|(extraStrategy))$/.exec(strategyField)
    : null;
  if (
    !match
    || !Number.isSafeInteger(Number(match[1]))
    || (match[2] !== undefined && !Number.isSafeInteger(Number(match[2])))
  ) {
    throw new Error("Select a valid script turn.");
  }
  return match[3]
    ? strategyField.replace(/extraStrategy$/, "extraCondition")
    : strategyField.replace(/_strategy$/, "_condition");
}

function isBinaryFlag(value) {
  return typeof value === "boolean" || (Number.isInteger(value) && (value === 0 || value === 1));
}

export function decodeNpCondition(value) {
  if (!Array.isArray(value) || value.length !== 4 || value[0] !== "np") {
    return null;
  }
  const parsed = [];
  for (const entry of value.slice(1)) {
    if (!Array.isArray(entry) || entry.length !== 3) return null;
    const [enabled, op, threshold] = entry;
    if (!isBinaryFlag(enabled)) return null;
    if (op !== "≥" && op !== "≤") return null;
    if (!Number.isInteger(threshold) || threshold < 0 || threshold > 300) return null;
    parsed.push({ enabled: Boolean(enabled), op, value: threshold });
  }
  return parsed;
}

export function decodeConditionCommand(value) {
  if (!Array.isArray(value) || !value.length) return null;
  if (value.length === 1 && value[0] === "End") {
    return { kind: "condition-end" };
  }
  if (value[0] !== "Start" || (value.length !== 3 && value.length !== 4)) {
    return null;
  }
  const [, rawMode, rawChecks] = value;
  if (!isBinaryFlag(rawMode)) return null;
  if (!Array.isArray(rawChecks) || rawChecks.some((flag) => !isBinaryFlag(flag))) {
    return null;
  }
  let npChecks = DEFAULT_NP_CHECKS.map((item) => ({ ...item }));
  let hasNp = false;
  if (value.length === 4) {
    const decodedNp = decodeNpCondition(value[3]);
    if (!decodedNp) return null;
    npChecks = decodedNp;
    hasNp = true;
  }
  return {
    kind: "condition-start",
    mode: rawMode ? 1 : 0,
    checks: rawChecks.map((flag) => Boolean(flag)),
    hasNp,
    npChecks,
  };
}

export function makeConditionStart({ mode = 1, checks = [], npChecks = null, includeNp = false } = {}) {
  if (!isBinaryFlag(mode)) throw new Error("Select a valid condition mode.");
  if (!Array.isArray(checks) || checks.some((flag) => !isBinaryFlag(flag))) {
    throw new Error("Condition checks must be booleans.");
  }
  const normalizedMode = mode ? 1 : 0;
  const normalizedChecks = checks.map((flag) => (flag ? 1 : 0));
  if (npChecks === null || npChecks === undefined) {
    return includeNp
      ? ["Start", normalizedMode, normalizedChecks, ["np", ...DEFAULT_NP_CHECKS.map((c) => [0, c.op, c.value])]]
      : ["Start", normalizedMode, normalizedChecks];
  }
  if (!Array.isArray(npChecks) || npChecks.length !== 3) {
    throw new Error("NP condition requires three servant thresholds.");
  }
  const formattedNp = npChecks.map((entry) => {
    if (!entry || typeof entry !== "object") throw new Error("Invalid NP threshold.");
    const threshold = Number(entry.value);
    if (!Number.isInteger(threshold) || threshold < 0 || threshold > 300) {
      throw new Error("NP threshold must be an integer between 0 and 300.");
    }
    const op = entry.op === "≤" ? "≤" : entry.op === "≥" ? "≥" : null;
    if (!op) throw new Error("NP operator must be ≥ or ≤.");
    return [entry.enabled ? 1 : 0, op, threshold];
  });
  const anyEnabled = formattedNp.some(([enabled]) => enabled === 1);
  if (!includeNp && !anyEnabled) {
    return ["Start", normalizedMode, normalizedChecks];
  }
  return ["Start", normalizedMode, normalizedChecks, ["np", ...formattedNp]];
}

export function makeConditionEnd() {
  return ["End"];
}

export function isMixedSkillCommand(value) {
  return decodeBasicSkill(value) !== null || decodeConditionCommand(value) !== null;
}

export function readMixedSkillEntries(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("Advanced skill sequence.");
  if (value.length > MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
  if (value.some((command) => !isMixedSkillCommand(command))) {
    throw new Error("Advanced skill sequence.");
  }
  return value;
}

function entryIndex(index, length) {
  if (!Number.isInteger(index) || index < 0 || index >= length) {
    throw new Error("Select a valid skill entry.");
  }
  return index;
}

export function changeMixedSkillSequence(value, edit) {
  if (!edit || typeof edit !== "object") throw new Error("Invalid skill edit.");
  if (edit.type === "clear") return [];
  const next = readMixedSkillEntries(value).slice();
  if (edit.type === "add-condition-start") {
    if (next.length >= MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
    next.push(makeConditionStart(edit));
    return next;
  }
  if (edit.type === "add-condition-end") {
    if (next.length >= MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
    next.push(makeConditionEnd());
    return next;
  }
  if (edit.type === "update-condition-start") {
    const idx = entryIndex(edit.index, next.length);
    if (decodeConditionCommand(next[idx])?.kind !== "condition-start") {
      throw new Error("Select a valid condition start block.");
    }
    next[idx] = makeConditionStart(edit);
    return next;
  }
  if (edit.type === "move") {
    const from = entryIndex(edit.index, next.length);
    const to = entryIndex(edit.to, next.length);
    next.splice(to, 0, next.splice(from, 1)[0]);
    return next;
  }
  if (edit.type === "remove") {
    next.splice(entryIndex(edit.index, next.length), 1);
    return next;
  }
  if (edit.type === "add") {
    if (next.length >= MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
    const [built] = changeSkillSequence(undefined, edit);
    next.push(built);
    return next;
  }
  if (edit.type === "update") {
    const idx = entryIndex(edit.index, next.length);
    if (!decodeBasicSkill(next[idx])) throw new Error("Select a valid skill entry.");
    const [built] = changeSkillSequence(undefined, { ...edit, type: "add" });
    next[idx] = built;
    return next;
  }
  throw new Error("Invalid skill edit.");
}

export function isValidConditionStrategyPayload(entry) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
  for (const key of ["card1", "card2", "card3"]) {
    const card = entry[key];
    if (!card || typeof card !== "object" || Array.isArray(card)) return false;
    if (
      card.type === undefined
      || !Array.isArray(card.cards)
      || card.criticalStar === undefined
      || typeof card.more_or_less !== "boolean"
    ) {
      return false;
    }
  }
  return Array.isArray(entry.breakpoint) && typeof entry.colorFirst === "boolean";
}
