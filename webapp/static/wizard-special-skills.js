import { decodeSpecialSkill, makeSpecialSkill, specialSkillColors } from "./special-skills-model.js";
import { KUKULKAN_SKILL, decodeKukulkan, makeKukulkan } from "./kukulkan-model.js";
import { decodeThirdSkill, makeThirdSkill } from "./third-skill-model.js";
import { HAKUNO_SKILL, decodeHakunoNeeds, makeHakunoNeeds } from "./hakuno-needs-model.js";
import { decodeSkillVariant, makeSkillVariant, skillVariantAvailable } from "./skill-variants-model.js";

const THIRD_OPTION_LABEL_KEYS = {
  Barghest: { 0: "Keep AoE NP", 1: "Single Target" },
  BBDubai: { 0: "Attack Type", 1: "Defense Type" },
  Soujyuro: { Q: "Quick", A: "Arts", B: "Buster" },
  Hakuno: { T: "Sky", D: "Earth", R: "Human" },
};

const VARIANT_OPTION_LABEL_KEYS = {
  VanGoghMiner: { Q: "Quick", A: "Arts", B: "Buster" },
  Dante: { A: "Paradiso (Arts Up)", B: "Inferno (Buster Up)" },
  Gyokuto: { All: "Moonlight (AoE NP)", One: "Sun (Single-Target NP)" },
  Charlotte: { "\u6280": "Skill Up", "\u66b4": "Critical Damage Up", "\u5b9d": "NP Damage Up" },
  Flora: { T: "Normal", D: "Underworld Garden" },
  Prelati: { "\u4e0d\u66ff\u6362": "Keep Saint Graph", "\u66ff\u6362": "Swap Saint Graph" },
  Lilith: { "\u4e0d\u4ed8\u4e0e\u5373\u6b7b": "No Instant Death", "\u4ed8\u4e0e\u5373\u6b7b": "Apply Instant Death" },
  Masi: { "\u65e0\u654c": "Invincible", "\u6bc5\u529b": "Guts" },
};

function optionsFromMap(labelMap, orderedKeys) {
  return orderedKeys.map((value) => ({ value, labelKey: labelMap[value] }));
}

const SPECIAL_SERVANT_SN = {
  SpaceIshtar: "1100900",
  Emiya: "200100",
  Kukulkan: "2501100",
  Barghest: "204900",
  Soujyuro: "704900",
  BBDubai: "2300600",
  HakunoFemale: "2300800",
  HakunoMale: "2300700",
  VanGoghMiner: "305600",
  Dante: "2801000",
  Gyokuto: "2301100",
  Charlotte: "603800",
  Flora: "1002000",
  PrelatiFrancois: "505600",
  PrelatiFrancesca: "505700",
  Lilith: "405900",
  Masi: "203300",
};

function matchesServantIdentity(sn, name, expectedSns, expectedNames) {
  if (sn && expectedSns.includes(sn)) return true;
  if (name && expectedNames.includes(name)) return true;
  return false;
}

export function resolveWizardSpecialSkill(servantOrName, slotIndex, skillIndex, server = "CH") {
  let canonicalServantName = "";
  let servantSn = "";
  if (typeof servantOrName === "string") {
    canonicalServantName = servantOrName;
  } else if (servantOrName && typeof servantOrName === "object") {
    if (typeof servantOrName.name === "string") canonicalServantName = servantOrName.name;
    if (servantOrName.sn != null) servantSn = String(servantOrName.sn);
  }
  if (!canonicalServantName && !servantSn) return null;
  if (!Number.isInteger(slotIndex) || slotIndex < 0 || slotIndex > 2) return null;
  if (!Number.isInteger(skillIndex) || skillIndex < 0 || skillIndex > 2) return null;

  const skillNum = slotIndex * 3 + skillIndex + 1;

  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.SpaceIshtar], ["太空伊什塔尔"]) && skillIndex === 1) {
    return {
      kind: "special-np",
      skillNum,
      negSkill: -skillNum,
      options: [
        { value: 1, labelKey: "Quick" },
        { value: 2, labelKey: "Arts" },
        { value: 3, labelKey: "Buster" },
      ],
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Emiya], ["卫宫"]) && skillIndex === 2) {
    return {
      kind: "special-np",
      skillNum,
      negSkill: -skillNum,
      options: [
        { value: 1, labelKey: "Arts" },
        { value: 2, labelKey: "Buster" },
      ],
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Kukulkan], ["库库尔坎"])) {
    return {
      kind: "kukulkan",
      named: KUKULKAN_SKILL,
      skillNum,
      needsTarget: skillIndex === 1,
      options: [
        { value: 0, labelKey: "Keep 10 Stars" },
        { value: 1, labelKey: "Use 10 Stars" },
      ],
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Barghest], ["UDK-巴格斯特"]) && skillIndex === 2) {
    return {
      kind: "third",
      named: "Barghest",
      skillNum,
      options: optionsFromMap(THIRD_OPTION_LABEL_KEYS.Barghest, [0, 1]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Soujyuro], ["静希草十郎"]) && skillIndex === 2) {
    return {
      kind: "third",
      named: "Soujyuro",
      skillNum,
      options: optionsFromMap(THIRD_OPTION_LABEL_KEYS.Soujyuro, ["Q", "A", "B"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.BBDubai], ["BB迪拜"]) && skillIndex === 2) {
    return {
      kind: "third",
      named: "BBDubai",
      skillNum,
      options: optionsFromMap(THIRD_OPTION_LABEL_KEYS.BBDubai, [0, 1]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.HakunoFemale, SPECIAL_SERVANT_SN.HakunoMale], ["岸波白野(女性)", "岸波白野(男性)"]) && skillIndex === 2) {
    return {
      kind: "third",
      named: "Hakuno",
      skillNum,
      options: optionsFromMap(THIRD_OPTION_LABEL_KEYS.Hakuno, ["T", "D", "R"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.HakunoFemale, SPECIAL_SERVANT_SN.HakunoMale], ["岸波白野(女性)", "岸波白野(男性)"]) && skillIndex === 0) {
    return {
      kind: "hakuno-needs",
      named: HAKUNO_SKILL,
      skillNum,
      options: [{ value: "once", labelKey: "Cast Once" }],
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.VanGoghMiner], ["梵高〔矿工〕"]) && skillIndex === 0) {
    return {
      kind: "variant",
      named: "VanGoghMiner",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.VanGoghMiner, ["Q", "A", "B"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Dante], ["但丁·阿利吉耶里"]) && skillIndex === 1) {
    return {
      kind: "variant",
      named: "Dante",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Dante, ["A", "B"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Gyokuto], ["玉兔"]) && skillIndex === 1) {
    return {
      kind: "variant",
      named: "Gyokuto",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Gyokuto, ["All", "One"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Charlotte], ["夏洛特·科黛"]) && skillIndex === 2 && skillVariantAvailable("Charlotte", server)) {
    return {
      kind: "variant",
      named: "Charlotte",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Charlotte, ["\u6280", "\u66b4", "\u5b9d"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Flora], ["芙萝拉"]) && skillIndex === 2) {
    return {
      kind: "variant",
      named: "Flora",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Flora, ["T", "D"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.PrelatiFrancois, SPECIAL_SERVANT_SN.PrelatiFrancesca], ["弗朗索瓦·普勒拉蒂", "弗兰切斯卡·普勒拉蒂"]) && skillIndex === 0) {
    return {
      kind: "variant",
      named: "Prelati",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Prelati, ["\u4e0d\u66ff\u6362", "\u66ff\u6362"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Lilith], ["莉莉丝(Rider)"]) && skillIndex === 2) {
    return {
      kind: "variant",
      named: "Lilith",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Lilith, ["\u4e0d\u4ed8\u4e0e\u5373\u6b7b", "\u4ed8\u4e0e\u5373\u6b7b"]),
    };
  }
  if (matchesServantIdentity(servantSn, canonicalServantName, [SPECIAL_SERVANT_SN.Masi], ["马嘶"]) && skillIndex === 0 && skillVariantAvailable("Masi", server)) {
    return {
      kind: "variant",
      named: "Masi",
      skillNum,
      options: optionsFromMap(VARIANT_OPTION_LABEL_KEYS.Masi, ["\u65e0\u654c", "\u6bc5\u529b"]),
    };
  }

  return null;
}

export function buildWizardSpecialCommand(spec, optionValue, target = null) {
  if (!spec || typeof spec !== "object") {
    throw new Error("Invalid special skill specification.");
  }
  if (spec.kind === "special-np") {
    return makeSpecialSkill(spec.negSkill, optionValue);
  }
  if (spec.kind === "kukulkan") {
    return makeKukulkan(spec.skillNum, optionValue, spec.needsTarget ? target : null);
  }
  if (spec.kind === "third") {
    return makeThirdSkill(spec.named, spec.skillNum, optionValue);
  }
  if (spec.kind === "hakuno-needs") {
    return makeHakunoNeeds(spec.skillNum, Array.isArray(optionValue) ? optionValue : []);
  }
  if (spec.kind === "variant") {
    return makeSkillVariant(spec.named, spec.skillNum, optionValue);
  }
  throw new Error(`Unsupported special skill kind: ${spec.kind}`);
}

export function extractServantSkillNumber(cmd) {
  if (typeof cmd === "number" && Number.isInteger(cmd) && cmd >= 1 && cmd <= 9) {
    return cmd;
  }
  if (!Array.isArray(cmd) || !cmd.length) return null;
  if (typeof cmd[0] === "number" && Number.isInteger(cmd[0])) {
    if (cmd[0] >= 1 && cmd[0] <= 9) return cmd[0];
    if (cmd[0] <= -1 && cmd[0] >= -9) return Math.abs(cmd[0]);
    return null;
  }
  if (typeof cmd[0] === "string" && typeof cmd[1] === "number" && Number.isInteger(cmd[1]) && cmd[1] >= 1 && cmd[1] <= 9) {
    return cmd[1];
  }
  return null;
}

export function formatSpecialSkillCommand(cmd, { skillName, slotLabel, translate }) {
  const tr = typeof translate === "function" ? translate : (s) => s;

  const specialNp = decodeSpecialSkill(cmd);
  if (specialNp) {
    const colors = specialSkillColors(specialNp.skill) || [];
    const colorKey = colors[specialNp.choice - 1] || String(specialNp.choice);
    return `${skillName(Math.abs(specialNp.skill))} · ${tr(colorKey)}`;
  }

  const kukulkan = decodeKukulkan(cmd);
  if (kukulkan) {
    const optLabel = tr(kukulkan.option === 1 ? "Use 10 Stars" : "Keep 10 Stars");
    const base = `${skillName(kukulkan.skill)} · ${optLabel}`;
    return kukulkan.target ? `${base} → ${slotLabel(kukulkan.target)}` : base;
  }

  const third = decodeThirdSkill(cmd);
  if (third) {
    const labelKey = THIRD_OPTION_LABEL_KEYS[third.named]?.[third.option];
    const optLabel = labelKey ? tr(labelKey) : String(third.option);
    return `${skillName(third.skill)} · ${optLabel}`;
  }

  const hakunoNeeds = decodeHakunoNeeds(cmd);
  if (hakunoNeeds) {
    const optLabel = hakunoNeeds.needs.length
      ? hakunoNeeds.needs.map((g) => g.join("+")).join(" / ")
      : tr("Cast Once");
    return `${skillName(hakunoNeeds.skill)} · ${optLabel}`;
  }

  const variant = decodeSkillVariant(cmd);
  if (variant) {
    const labelKey = VARIANT_OPTION_LABEL_KEYS[variant.named]?.[variant.option];
    const optLabel = labelKey ? tr(labelKey) : String(variant.option);
    return `${skillName(variant.skill)} · ${optLabel}`;
  }

  return null;
}

export function applyOrderChange(lineup, cmd) {
  if (
    Array.isArray(cmd)
    && cmd.length === 3
    && typeof cmd[0] === "number"
    && cmd[0] >= 10
    && cmd[0] <= 12
    && Number.isInteger(cmd[1])
    && Number.isInteger(cmd[2])
    && cmd[1] >= 1 && cmd[1] <= 6
    && cmd[2] >= 1 && cmd[2] <= 6
    && cmd[1] !== cmd[2]
  ) {
    const a = cmd[1] - 1;
    const b = cmd[2] - 1;
    const tmp = lineup[a];
    lineup[a] = lineup[b];
    lineup[b] = tmp;
  }
}

export function applyTurnReplace(lineup, replaceMap) {
  if (!replaceMap || typeof replaceMap !== "object" || Array.isArray(replaceMap)) return;
  const snapshot = [...lineup];
  for (const [rawKey, rawValue] of Object.entries(replaceMap)) {
    const targetIdx = Number(rawKey) - 1;
    if (!Number.isInteger(targetIdx) || targetIdx < 0 || targetIdx > 5) continue;
    if (rawValue === null) {
      lineup[targetIdx] = null;
    } else if (typeof rawValue === "number" && Number.isInteger(rawValue) && rawValue >= 1 && rawValue <= 6) {
      lineup[targetIdx] = snapshot[rawValue - 1];
    }
  }
}

export function computeLineupBefore(config, targetWave, stopBeforeSkillIndex = Infinity) {
  const lineup = [0, 1, 2, 3, 4, 5];
  if (!config || typeof config !== "object") return lineup;
  for (let w = 1; w <= targetWave; w += 1) {
    const turns = Math.max(1, Number(config[`round${w}_turns`] || 0));
    const maxTurn = w < targetWave ? turns : 1;
    for (let turn = 0; turn < maxTurn; turn += 1) {
      const skills = config[`round${w}_turn${turn}_skill`];
      if (Array.isArray(skills)) {
        const limit = w === targetWave && turn === 0
          ? Math.min(skills.length, stopBeforeSkillIndex)
          : skills.length;
        let conditionDepth = 0;
        for (let i = 0; i < limit; i += 1) {
          const cmd = skills[i];
          if (Array.isArray(cmd) && cmd[0] === "Start") {
            conditionDepth += 1;
            continue;
          }
          if (Array.isArray(cmd) && cmd[0] === "End") {
            conditionDepth = Math.max(0, conditionDepth - 1);
            continue;
          }
          if (conditionDepth === 0) {
            applyOrderChange(lineup, cmd);
          }
        }
      }
      if (w < targetWave || turn < maxTurn - 1) {
        applyTurnReplace(lineup, config[`round${w}_turn${turn}_replace`]);
      }
    }
    if (w < targetWave) {
      if (Array.isArray(config[`round${w}_extraSkill`])) {
        let conditionDepth = 0;
        for (const cmd of config[`round${w}_extraSkill`]) {
          if (Array.isArray(cmd) && cmd[0] === "Start") {
            conditionDepth += 1;
            continue;
          }
          if (Array.isArray(cmd) && cmd[0] === "End") {
            conditionDepth = Math.max(0, conditionDepth - 1);
            continue;
          }
          if (conditionDepth === 0) {
            applyOrderChange(lineup, cmd);
          }
        }
      }
      applyTurnReplace(lineup, config[`round${w}_extraReplace`]);
    }
  }
  return lineup;
}
