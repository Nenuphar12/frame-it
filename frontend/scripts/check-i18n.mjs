// Verifies that every static i18n key used in src/ exists in the English catalog.
// Dynamic keys (template literals) are listed in DYNAMIC_PREFIXES and must have at least one entry.
// Every other catalog must hold exactly the English keys, with the same {{placeholders}}.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const catalog = JSON.parse(readFileSync("src/i18n/locales/en/common.json", "utf8"));
const DYNAMIC_PREFIXES = [
  "errors",
  "upload.status",
  "photos.warnings",
  "photos.inboxState",
  "devices.roles",
  "devices.roleHints",
  "settings.themes",
  "settings.languages",
  "artworks.filters",
  "artworks.sorts",
  "artworks.statuses",
  "artworks.tiers",
  "artworks.tierHints",
  "artworks.statusHints",
  "artworks.create.placements",
  "editor.tabs",
  "editor.sides",
  "editor.lock",
  "editor.placement",
  "editor.ratios",
  "editor.alternatives",
  "editor.colors.kinds",
  "editor.history.reasons",
  "editor.arrange.align",
  "editor.captions.anchors",
  "filters.fields",
  "filters.ops",
  "collections.kinds",
  "trash.cascade",
  "archive.state",
  "archive.importState",
  "archive.policy",
  "archive.kind",
  "archive.status",
  "archive.column",
  "activity.kinds",
  "activity.states",
  "display.intervals",
  "display.phases",
];

const has = (key) => {
  let node = catalog;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node !== "object") return false;
    node = node[part] ?? node[`${part}_one`];
  }
  return node !== undefined;
};

const files = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) files.push(path);
  }
};
walk("src");

const patterns = [
  /\bt\(\s*"([a-zA-Z][\w.]+)"/g,
  /\b(?:label|group|titleKey)[:=]\s*"([a-z][\w]*\.[\w.]+)"/g,
  /"(auth\.default\w+)"/g,
];
const missing = [];
for (const file of files) {
  const source = readFileSync(file, "utf8");
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      if (!has(match[1])) missing.push(`${file}: ${match[1]}`);
    }
  }
}
for (const prefix of DYNAMIC_PREFIXES) {
  if (!has(prefix)) missing.push(`dynamic prefix: ${prefix}`);
}
const flatten = (node, prefix = "", out = new Map()) => {
  for (const [key, value] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else flatten(value, path, out);
  }
  return out;
};
const placeholders = (text) =>
  [...text.matchAll(/\{\{(\w+)\}\}/g)]
    .map((m) => m[1])
    .sort()
    .join(",");
const english = flatten(catalog);
for (const language of readdirSync("src/i18n/locales")) {
  if (language === "en") continue;
  const other = flatten(
    JSON.parse(readFileSync(`src/i18n/locales/${language}/common.json`, "utf8")),
  );
  for (const [key, text] of english) {
    if (!other.has(key)) missing.push(`${language}: ${key}`);
    else if (placeholders(other.get(key)) !== placeholders(text)) {
      missing.push(`${language}: ${key} — placeholders {${placeholders(text)}} expected`);
    }
  }
  for (const key of other.keys()) {
    if (!english.has(key)) missing.push(`${language}: ${key} — not in the English catalog`);
  }
}
if (missing.length) {
  console.error(`Missing i18n keys:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log(
  `i18n OK (${files.length} files checked, ${readdirSync("src/i18n/locales").length} languages)`,
);
