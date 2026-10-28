export const MAX_SKILL_COMMANDS = 1000;
export const COMMAND_SPELLS = Object.freeze({
  np: "\u4ee4\u5492\u00b7\u5b9d\u5177\u89e3\u653e",
  heal: "\u4ee4\u5492\u00b7\u7075\u57fa\u4fee\u590d",
});

export function isCommandSpell(value) {
  return Object.values(COMMAND_SPELLS).includes(value);
}

export function skillField(strategyField) {
  const match = typeof strategyField === "string"
    ? /^round(0|[1-9][0-9]*)_(?:turn(0|[1-9][0-9]*)_strategy|(extraStrategy))$/.exec(strategyField) : null;
  if (!match || !Number.isSafeInteger(Number(match[1]))
      || (match[2] !== undefined && !Number.isSafeInteger(Number(match[2])))) {
    throw new Error("Select a valid script turn.");
  }
  return match[3] ? strategyField.replace(/extraStrategy$/, "extraSkill") : strategyField.replace(/_strategy$/, "_skill");
}

function validExchange(skill, positions) {
  return Number.isInteger(skill) && skill >= 10 && skill <= 12
    && Array.isArray(positions) && positions.length === 2
    && positions.every((position) => Number.isInteger(position) && position >= 1 && position <= 6)
    && (positions[0] <= 3) !== (positions[1] <= 3);
}

export function decodeBasicSkill(value) {
  const paired = Array.isArray(value);
  if (paired && value.length === 3) {
    const [skill, ...swap] = value;
    return validExchange(skill, swap) ? { skill, target: null, swap } : null;
  }
  if (paired && value.length !== 2) return null;
  const skill = paired ? value[0] : value;
  const target = paired ? value[1] : null;
  if (isCommandSpell(skill)) {
    return Number.isInteger(target) && target >= 1 && target <= 3 ? { skill, target } : null;
  }
  if (!Number.isInteger(skill) || skill < 1 || skill > 13
      || (skill === 13 && target === null)
      || (target !== null && (!Number.isInteger(target) || target < 1 || target > (skill === 13 ? 6 : 3)))) return null;
  return { skill, target };
}

export function readBasicSkills(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("Invalid skill sequence.");
  if (value.length > MAX_SKILL_COMMANDS) throw new Error("Skill sequence exceeds 1,000 entries.");
  if (value.some((command) => decodeBasicSkill(command) === null)) throw new Error("Advanced skill sequence.");
  return value;
}

function command(skill, target = null, swap) {
  if (isCommandSpell(skill)) {
    if (swap !== undefined || !Number.isInteger(target) || target < 1 || target > 3) {
      throw new Error("Select a valid command spell target.");
    }
    return [skill, target];
  }
  if (!Number.isInteger(skill) || skill < 1 || skill > 13) throw new Error("Select a valid skill.");
  if (swap !== undefined) {
    if (target !== null || !validExchange(skill, swap)) throw new Error("Select a frontline and a reserve servant.");
    return [skill, ...swap];
  }
  if ((skill === 13 && target === null)
      || (target !== null && (!Number.isInteger(target) || target < 1 || target > (skill === 13 ? 6 : 3)))) {
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
    next.push(command(edit.skill === undefined ? 1 : edit.skill, edit.target, edit.swap));
  } else if (edit.type === "update") {
    next[entryIndex(edit.index, next.length)] = command(edit.skill, edit.target, edit.swap);
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
