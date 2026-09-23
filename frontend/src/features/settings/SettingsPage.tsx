import { useTranslation } from "react-i18next";

import {
  useArtworkDefaults,
  useFrameStyles,
  useRecipes,
  useSetArtworkDefaults,
  useSystemInfo,
} from "@/api/queries";
import { useTheme, type ThemePreference } from "@/app/theme";
import { SUPPORTED_LANGUAGES, setLanguage } from "@/i18n";
import { PageHeader } from "@/shared/ui/Misc";

/** The formats offered as a default; the editor has the full chip row (docs/simple-editor.md §6.2). */
const DEFAULT_FORMATS = ["fill", "original", "1:1", "5:4", "4:3", "3:2", "16:9"] as const;

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { preference, setPreference } = useTheme();
  const info = useSystemInfo();
  const defaults = useArtworkDefaults();
  const styles = useFrameStyles();
  const recipes = useRecipes();
  const setDefaults = useSetArtworkDefaults();
  const current = defaults.data;

  return (
    <div className="flex h-full flex-col">
      <PageHeader title={t("nav.settings")} />
      <div className="max-w-2xl flex-1 space-y-6 overflow-y-auto p-5">
        <section className="space-y-3 rounded-lg border border-border bg-panel p-4">
          <h2 className="text-sm font-semibold">{t("settings.appearance")}</h2>
          <label className="flex items-center justify-between gap-4 text-sm">
            {t("settings.theme")}
            <select
              value={preference}
              onChange={(event) => setPreference(event.target.value as ThemePreference)}
              className="rounded-md border border-border bg-bg px-2 py-1"
            >
              {(["dark", "light", "system"] as const).map((value) => (
                <option key={value} value={value}>
                  {t(`settings.themes.${value}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center justify-between gap-4 text-sm">
            {t("settings.language")}
            <select
              value={i18n.language}
              onChange={(event) => setLanguage(event.target.value)}
              className="rounded-md border border-border bg-bg px-2 py-1"
            >
              {SUPPORTED_LANGUAGES.map((lang) => (
                <option key={lang} value={lang}>
                  {t(`settings.languages.${lang}`)}
                </option>
              ))}
            </select>
          </label>
        </section>
        <section className="space-y-3 rounded-lg border border-border bg-panel p-4">
          <h2 className="text-sm font-semibold">{t("settings.artworkDefaults")}</h2>
          <p className="text-xs text-muted">{t("settings.artworkDefaultsHint")}</p>
          <label className="flex items-center justify-between gap-4 text-sm">
            {t("artworks.create.style")}
            <select
              value={current?.style_id ?? ""}
              disabled={!current}
              onChange={(event) =>
                current && setDefaults.mutate({ ...current, style_id: event.target.value })
              }
              className="rounded-md border border-border bg-bg px-2 py-1"
            >
              {(styles.data ?? []).map((style) => (
                <option key={style.id} value={style.id}>
                  {style.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center justify-between gap-4 text-sm">
            {t("settings.defaultRecipe")}
            <select
              value={current?.recipe_id ?? ""}
              disabled={!current}
              onChange={(event) =>
                current && setDefaults.mutate({ ...current, recipe_id: event.target.value || null })
              }
              className="rounded-md border border-border bg-bg px-2 py-1"
            >
              <option value="">{t("settings.automatic")}</option>
              {(recipes.data ?? []).map((recipe) => (
                <option key={recipe.id} value={recipe.id}>
                  {t(recipe.name_key, { defaultValue: recipe.id })} ({recipe.count})
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center justify-between gap-4 text-sm">
            {t("settings.defaultFormat")}
            <select
              value={current?.format ?? ""}
              disabled={!current}
              onChange={(event) =>
                current && setDefaults.mutate({ ...current, format: event.target.value || null })
              }
              className="rounded-md border border-border bg-bg px-2 py-1"
            >
              <option value="">{t("settings.automatic")}</option>
              {DEFAULT_FORMATS.map((value) => (
                <option key={value} value={value}>
                  {t(`editor.simple.formats.${value}`, { defaultValue: value })}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-muted">{t("settings.defaultRecipeHint")}</p>
        </section>
        <section className="space-y-2 rounded-lg border border-border bg-panel p-4 text-sm">
          <h2 className="font-semibold">{t("settings.about")}</h2>
          {info.data && (
            <dl className="grid grid-cols-[10rem_1fr] gap-1 text-muted">
              <dt>{t("settings.version")}</dt>
              <dd className="text-text">{info.data.version}</dd>
              <dt>{t("settings.publicUrl")}</dt>
              <dd className="text-text">{info.data.public_url}</dd>
              <dt>libvips</dt>
              <dd className="text-text">{info.data.capabilities.libvips_version}</dd>
            </dl>
          )}
          <p className="pt-2 text-xs text-muted">{t("settings.attribution")}</p>
        </section>
      </div>
    </div>
  );
}
