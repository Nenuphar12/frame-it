import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en/common.json";
import fr from "./locales/fr/common.json";

export const SUPPORTED_LANGUAGES = ["en", "fr"] as const;
type Language = (typeof SUPPORTED_LANGUAGES)[number];
const STORAGE_KEY = "tf.language";

function supported(language: string | null | undefined): Language | null {
  const base = language?.toLowerCase().split("-")[0];
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(base ?? "")
    ? (base as Language)
    : null;
}

/** The choice made in Settings, else the browser's — a phone has no Settings page to choose in. */
function initialLanguage(): Language {
  try {
    const stored = supported(localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch {
    /* storage unavailable */
  }
  for (const language of navigator.languages ?? [navigator.language]) {
    const match = supported(language);
    if (match) return match;
  }
  return "en";
}

type Catalog = { [key: string]: string | Catalog };

/**
 * French has a third plural form, `many`, for exact millions ("1 000 000 de photos"). It reads like
 * `other` here, so the catalog leaves it out and this fills it in — otherwise i18next would fall
 * back to the English sentence for those counts.
 */
function withMany(catalog: Catalog): Catalog {
  const out: Catalog = {};
  for (const [key, value] of Object.entries(catalog)) {
    out[key] = typeof value === "string" ? value : withMany(value);
    if (typeof value === "string" && key.endsWith("_other")) {
      const many = `${key.slice(0, -"_other".length)}_many`;
      if (!(many in catalog)) out[many] = value;
    }
  }
  return out;
}

i18n.on("languageChanged", (language) => {
  document.documentElement.lang = language;
});

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fr: { translation: withMany(fr) } },
  lng: initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(language: string) {
  void i18n.changeLanguage(language);
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    /* storage unavailable */
  }
}

export default i18n;
