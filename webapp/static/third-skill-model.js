const OPTIONS = {
  Barghest: [0, 1],
  BBDubai: [0, 1],
  Soujyuro: ["Q", "A", "B"],
  Hakuno: ["T", "D", "R"],
};

export const THIRD_SKILL_NAMES = Object.freeze(Object.keys(OPTIONS));

export function thirdSkillOptions(named) {
  return typeof named === "string" && Object.hasOwn(OPTIONS, named) ? OPTIONS[named].slice() : null;
}

export function decodeThirdSkill(command) {
  if (!Array.isArray(command) || command.length !== 3) return null;
  const [named, skill, option] = command;
  const options = thirdSkillOptions(named);
  if (!options || !Number.isInteger(skill) || skill < 3 || skill > 9 || skill % 3 !== 0
      || !options.includes(option)) return null;
  return { named, skill, option, target: null };
}

export function makeThirdSkill(named, skill, option) {
  const command = [named, skill, option];
  if (!decodeThirdSkill(command)) throw new Error("Select valid third-skill parameters.");
  return command;
}
