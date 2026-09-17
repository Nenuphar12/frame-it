import { create } from "zustand";

export type ThemePreference = "dark" | "light" | "system";
const STORAGE_KEY = "tf.theme";

function read(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    /* storage unavailable */
  }
  return "dark";
}

function apply(preference: ThemePreference) {
  const resolved =
    preference === "system"
      ? window.matchMedia("(prefers-color-scheme: light)").matches
        ? "light"
        : "dark"
      : preference;
  document.documentElement.dataset.theme = resolved;
}

interface ThemeState {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  preference: read(),
  setPreference(preference) {
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      /* storage unavailable */
    }
    apply(preference);
    set({ preference });
  },
  toggle() {
    const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    get().setPreference(current === "light" ? "dark" : "light");
  },
}));

export function initTheme() {
  apply(useTheme.getState().preference);
  window
    .matchMedia("(prefers-color-scheme: light)")
    .addEventListener("change", () => apply(useTheme.getState().preference));
}
