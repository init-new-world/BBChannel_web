export const KUKULKAN_SKILL = "Kukulkan";

function validSkill(skill) {
  return Number.isInteger(skill) && skill >= 1 && skill <= 9;
}

export function kukulkanNeedsTarget(skill) {
  return validSkill(skill) && skill % 3 === 2;
}

export function decodeKukulkan(command) {
  if (!Array.isArray(command) || command[0] !== KUKULKAN_SKILL) return null;
  const [, skill, option] = command;
  if (!validSkill(skill) || !Number.isInteger(option) || option < 0 || option > 1) return null;
  const needsTarget = kukulkanNeedsTarget(skill);
  if (command.length !== (needsTarget ? 4 : 3)) return null;
  const target = needsTarget ? command[3] : null;
  if (needsTarget && (!Number.isInteger(target) || target < 1 || target > 3)) return null;
  return { named: KUKULKAN_SKILL, skill, option, target };
}

export function makeKukulkan(skill, option, target = null) {
  const needsTarget = kukulkanNeedsTarget(skill);
  if (!needsTarget && target !== null) throw new Error("Select valid Kukulkan skill parameters.");
  const command = [KUKULKAN_SKILL, skill, option, ...(needsTarget ? [target] : [])];
  if (!decodeKukulkan(command)) throw new Error("Select valid Kukulkan skill parameters.");
  return command;
}
