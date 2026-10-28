import { applyEdits, modify, parseTree } from "./vendor/jsonc-parser.js";

export function parseJsonSource(source) {
  if (typeof source !== "string") throw new Error("Invalid script JSON.");
  const errors = [];
  let root;
  try {
    root = parseTree(source, errors, { disallowComments: true, allowTrailingComma: false, allowEmptyContent: false });
  } catch {
    throw new Error("Invalid script JSON.");
  }
  if (errors.length || !root) throw new Error("Invalid script JSON.");
  return root;
}

export function readJsonField(source, field, ambiguityError) {
  const root = parseJsonSource(source);
  if (root.type !== "object") throw new Error("Invalid script JSON.");
  const properties = root.children.filter((property) => property.children[0].value === field);
  if (properties.length > 1) throw new Error(ambiguityError);
  const node = properties[0]?.children[1];
  const value = node ? JSON.parse(source.slice(node.offset, node.offset + node.length)) : undefined;
  return {
    field, node, value,
    replace(next) {
      if (node) {
        return applyEdits(source, [{ offset: node.offset, length: node.length, content: JSON.stringify(next) }]);
      }
      return applyEdits(source, modify(source, [field], next, {
        formattingOptions: { insertSpaces: true, tabSize: 2, eol: source.includes("\r\n") ? "\r\n" : "\n" },
      }));
    },
    remove() {
      return applyEdits(source, modify(source, [field], undefined, {
        formattingOptions: { insertSpaces: true, tabSize: 2, eol: source.includes("\r\n") ? "\r\n" : "\n" },
      }));
    },
    replaceSource(nextSource) {
      parseJsonSource(nextSource);
      if (node) {
        return applyEdits(source, [{ offset: node.offset, length: node.length, content: nextSource }]);
      }
      // Insert a placeholder without round-tripping the raw replacement through JS numbers.
      const scaffold = this.replace(null);
      return readJsonField(scaffold, field, ambiguityError).replaceSource(nextSource);
    },
  };
}
