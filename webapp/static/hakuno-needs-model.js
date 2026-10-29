export const HAKUNO_SKILL = "Hakuno";
export const MAX_HAKUNO_COMBINATIONS = 1000;

export function isHakunoCardCode(code) {
  return typeof code === "string" && /^(?:[1-3][ABQ]|(?:[1-3][ABQ])?S(?:0|[1-9][0-9]*))$/.test(code);
}

function validSkill(skill) {
  return Number.isInteger(skill) && skill >= 1 && skill <= 9 && skill % 3 === 1;
}

export function readHakunoNeeds(needs) {
  if (!Array.isArray(needs)) throw new Error("Invalid Hakuno card needs.");
  if (needs.length > MAX_HAKUNO_COMBINATIONS) throw new Error("Hakuno needs exceed 1,000 combinations.");
  for (const group of needs) {
    if (!Array.isArray(group)) throw new Error("Invalid Hakuno card needs.");
    if (group.length > 5) throw new Error("Hakuno combinations cannot exceed five cards.");
    for (const code of group) {
      if (!isHakunoCardCode(code)) throw new Error("Select a valid Hakuno card code.");
    }
  }
  return needs.map((group) => group.slice());
}

export function decodeHakunoNeeds(command) {
  if (!Array.isArray(command) || command.length !== 3 || command[0] !== HAKUNO_SKILL || !validSkill(command[1])) return null;
  try {
    return { named: HAKUNO_SKILL, skill: command[1], needs: readHakunoNeeds(command[2]), target: null };
  } catch {
    return null;
  }
}

export function makeHakunoNeeds(skill, needs) {
  if (!validSkill(skill)) throw new Error("Select a valid Hakuno skill.");
  return [HAKUNO_SKILL, skill, readHakunoNeeds(needs)];
}

function index(value, length, message) {
  if (!Number.isInteger(value) || value < 0 || value >= length) throw new Error(message);
  return value;
}

export function changeHakunoNeeds(needs, edit) {
  if (!edit || typeof edit !== "object") throw new Error("Invalid Hakuno card edit.");
  if (edit.type === "clear") return [];
  const next = readHakunoNeeds(needs);
  if (edit.type === "add") {
    if (next.length >= MAX_HAKUNO_COMBINATIONS) throw new Error("Hakuno needs exceed 1,000 combinations.");
    next.push(["1B"]);
    return next;
  }
  if (!["remove", "move", "add-card", "update-card", "remove-card"].includes(edit.type)) {
    throw new Error("Invalid Hakuno card edit.");
  }
  const at = index(edit.index, next.length, "Select a valid Hakuno combination.");
  const group = next[at];
  if (edit.type === "remove") {
    next.splice(at, 1);
  } else if (edit.type === "move") {
    const to = index(edit.to, next.length, "Select a valid Hakuno combination.");
    next.splice(to, 0, next.splice(at, 1)[0]);
  } else if (edit.type === "add-card") {
    if (group.length >= 5) throw new Error("Hakuno combinations cannot exceed five cards.");
    const code = edit.code === undefined ? "1B" : edit.code;
    if (!isHakunoCardCode(code)) throw new Error("Select a valid Hakuno card code.");
    group.push(code);
  } else {
    const card = index(edit.card, group.length, "Select a valid Hakuno card.");
    if (edit.type === "update-card") {
      if (!isHakunoCardCode(edit.code)) throw new Error("Select a valid Hakuno card code.");
      group[card] = edit.code;
    } else {
      group.splice(card, 1);
      if (!group.length) next.splice(at, 1);
    }
  }
  return next;
}
