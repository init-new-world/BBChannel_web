export const MAX_SKILL_COMMANDS = 1000;

export function skillField(strategyField) {
  const match = typeof strategyField === "string"
    ? /^round(0|[1-9][0-9]*)_(?:turn(0|[1-9][0-9]*)_strategy|(extraStrategy))$/.exec(strategyField) : null;
  if (!match || !Number.isSafeInteger(Number(match[1]))
      || (match[2] !== undefined && !Number.isSafeInteger(Number(match[2])))) {
    throw new Error("Select a valid script turn.");
  }
  return match[3] ? strategyField.replace(/extraStrategy$/, "extraSkill") : strategyField.replace(/_strategy$/, "_skill");
}

export function decodeBasicSkill(value) {
  const paired = Array.isArray(value);
  if (paired && value.length !== 2) return null;
  const skill = paired ? value[0] : value;
  const target = paired ? value[1] : null;
  if (!Number.isInteger(skill) || skill < 1 || skill > 12
      || (target !== null && (!Number.isInteger(target) || target < 1 || target > 3))) return null;
  return { skill, target };
}

export function readBasicSkills(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("Invalid skill sequence.");
  if (value.length > MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
  if (value.some((command) => decodeBasicSkill(command) === null)) throw new Error("Advanced skill sequence.");
  return value;
}

function command(skill, target = null) {
  if (!Number.isInteger(skill) || skill < 1 || skill > 12) throw new Error("Select a valid skill.");
  if (target !== null && (!Number.isInteger(target) || target < 1 || target > 3)) {
    throw new Error("Select a valid skill target.");
  }
  return target === null ? skill : [skill, target];
}

function entryIndex(index, length) {
  if (!Number.isInteger(index) || index < 0 || index >= length) throw new Error("Select a valid skill entry.");
  return index;
}

export function changeSkillSequence(value, edit) {
  if (!edit || typeof edit !== "object") throw new Error("Invalid skill edit.");
  if (edit.type === "clear") return [];
  const next = readBasicSkills(value).slice();
  if (edit.type === "add") {
    if (next.length >= MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
    next.push(command(edit.skill === undefined ? 1 : edit.skill, edit.target));
  } else if (edit.type === "update") {
    next[entryIndex(edit.index, next.length)] = command(edit.skill, edit.target);
  } else if (edit.type === "remove") {
    next.splice(entryIndex(edit.index, next.length), 1);
  } else if (edit.type === "move") {
    const from = entryIndex(edit.index, next.length);
    const to = entryIndex(edit.to, next.length);
    next.splice(to, 0, next.splice(from, 1)[0]);
  } else {
    throw new Error("Invalid skill edit.");
  }
  return next;
}
