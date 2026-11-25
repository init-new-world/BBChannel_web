const VARIANT_REPLACEMENTS = [
  [/卡斯特/g, "caster"],
  [/丝卡蒂/g, "斯卡蒂"],
  [/阿尔托利亚/g, "阿尔托莉雅"],
  [/伊斯塔/g, "伊什塔尔"],
];

const SEPARATOR_PATTERN = /[\s·・•=＝\-－—_〔〕[\]()（）「」『』,，.。/／]+/g;

export function normalizeSearchText(raw) {
  if (typeof raw !== "string" || !raw) return "";
  let text = raw.normalize("NFKC").toLowerCase().trim();
  for (const [pattern, replacement] of VARIANT_REPLACEMENTS) {
    text = text.replace(pattern, replacement);
  }
  return text.replace(SEPARATOR_PATTERN, "");
}

export function matchesNormalizedQuery(haystack, query) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) return true;
  if (typeof haystack !== "string" || !haystack) return false;
  const rawLower = haystack.toLowerCase();
  const queryLower = String(query).trim().toLowerCase();
  if (queryLower && rawLower.includes(queryLower)) return true;
  return normalizeSearchText(haystack).includes(normalizedQuery);
}
