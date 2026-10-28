const ISHTAR_COLORS = Object.freeze(["Quick", "Arts", "Buster"]);
const EMIYA_COLORS = Object.freeze(["Arts", "Buster"]);

export function specialSkillColors(skill) {
  if (!Number.isInteger(skill) || skill > -1 || skill < -9 || Math.abs(skill) % 3 === 1) return null;
  return Math.abs(skill) % 3 === 0 ? EMIYA_COLORS : ISHTAR_COLORS;
}

export function decodeSpecialSkill(command) {
  if (!Array.isArray(command) || command.length !== 2) return null;
  const [skill, choice] = command;
  const colors = specialSkillColors(skill);
  if (!colors || !Number.isInteger(choice) || choice < 1 || choice > colors.length) return null;
  return { skill, target: null, choice };
}

export function makeSpecialSkill(skill, choice) {
  if (!decodeSpecialSkill([skill, choice])) throw new Error("Select a valid NP color.");
  return [skill, choice];
}

export function specialSkillChoice(previous, skill) {
  const colors = specialSkillColors(skill);
  if (!colors) throw new Error("Select a valid NP color.");
  const decoded = decodeSpecialSkill(previous);
  const color = decoded ? specialSkillColors(decoded.skill)[decoded.choice - 1] : null;
  return Math.max(colors.indexOf(color), 0) + 1;
}
