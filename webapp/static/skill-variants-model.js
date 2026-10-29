const RULES = {
  VanGoghMiner: { first: 1, options: ["Q", "A", "B"] },
  Dante: { first: 2, options: ["A", "B"] },
  Gyokuto: { first: 2, options: ["All", "One"] },
  Charlotte: { first: 3, options: ["\u6280", "\u66b4", "\u5b9d"], servers: ["CH", "JP"] },
  Flora: { first: 3, options: ["T", "D"] },
};

export const SKILL_VARIANT_NAMES = Object.freeze(Object.keys(RULES));

function ruleFor(named) {
  return typeof named === "string" && Object.hasOwn(RULES, named) ? RULES[named] : null;
}

export function skillVariantOptions(named) {
  return ruleFor(named)?.options.slice() ?? null;
}

export function skillVariantNumbers(named) {
  const rule = ruleFor(named);
  return rule ? [rule.first, rule.first + 3, rule.first + 6] : null;
}

// Availability gates new selections, not decoding an existing command.
export function skillVariantAvailable(named, server) {
  const rule = ruleFor(named);
  return Boolean(rule && (!rule.servers || (typeof server === "string" && rule.servers.includes(server.toUpperCase()))));
}

export function decodeSkillVariant(command) {
  if (!Array.isArray(command) || command.length !== 3) return null;
  const [named, skill, option] = command;
  const rule = ruleFor(named);
  if (!rule || !Number.isInteger(skill) || skill < 1 || skill > 9 || (skill - 1) % 3 !== rule.first - 1
      || !rule.options.includes(option)) return null;
  return { named, skill, option, target: null };
}

export function makeSkillVariant(named, skill, option) {
  const command = [named, skill, option];
  if (!decodeSkillVariant(command)) throw new Error("Select valid variant-skill parameters.");
  return command;
}
