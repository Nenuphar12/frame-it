import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en/common.json";

export const SUPPORTED_LANGUAGES = ["en"] as const;
const STORAGE_KEY = "tf.language";

function initialLanguage(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && (SUPPORTED_LANGUAGES as readonly string[]).includes(stored)) return stored;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
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
