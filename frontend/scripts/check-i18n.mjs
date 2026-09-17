// Verifies that every static i18n key used in src/ exists in the English catalog.
// Dynamic keys (template literals) are listed in DYNAMIC_PREFIXES and must have at least one entry.
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
  "artworks.statuses",
  "artworks.tiers",
  "artworks.tierHints",
  "artworks.create.placements",
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
if (missing.length) {
  console.error(`Missing i18n keys:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log(`i18n OK (${files.length} files checked)`);
