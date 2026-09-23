import { Link } from "@tanstack/react-router";
import { FolderOpen, Heart, ImagePlus, Images, Monitor, Sun } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tag } from "@/api/client";
import { useCollections, useMe } from "@/api/queries";
import { useTheme } from "@/app/theme";
import { TagPicker } from "@/features/tags/TagPicker";
import { UploadRow } from "@/features/upload/UploadTray";
import { useUploadSummary } from "@/features/upload/useUploadSummary";
import { useUploads } from "@/features/upload/uploadStore";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";

/**
 * Phone companion: pick photos, attach metadata, follow progress.
 * Two pickers (see docs/research/phone-uploads.md): the photo picker is the most convenient, the
 * file picker is the fallback that keeps full EXIF (incl. GPS) when the photo picker strips it.
 */
export function MobileUploadPage() {
  const { t } = useTranslation();
  const me = useMe();
  const collections = useCollections();
  // A smart collection has no items of its own: only manual ones can be picked at upload.
  const manualCollections = (collections.data ?? []).filter((c) => c.kind === "manual");
  const items = useUploads((s) => s.items);
  const add = useUploads((s) => s.add);
  const clearFinished = useUploads((s) => s.clearFinished);
  const summary = useUploadSummary();
  const toggleTheme = useTheme((s) => s.toggle);
  const [tags, setTags] = useState<Tag[]>([]);
  const [collectionIds, setCollectionIds] = useState<string[]>([]);
  const [favorite, setFavorite] = useState(false);

  const pick = (mode: "photos" | "files") => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    if (mode === "photos") input.accept = "image/*";
    input.onchange = () =>
      add(Array.from(input.files ?? []), {
        tag_ids: tags.map((tag) => tag.id),
        collection_ids: collectionIds,
        favorite,
      });
    input.click();
  };

  return (
    <div className="mx-auto flex min-h-full max-w-lg flex-col gap-5 px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">{t("mobile.title")}</h1>
          <p className="text-xs text-muted">{me.data?.device_name ?? t("mobile.thisDevice")}</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleTheme}
            className="rounded-md p-2 text-muted hover:text-text"
            aria-label={t("commands.toggleTheme")}
          >
            <Sun size={18} />
          </button>
          <Link
            to="/m/browse"
            className="rounded-md p-2 text-muted hover:text-text"
            aria-label={t("mobile.browse")}
          >
            <Images size={18} />
          </Link>
          {me.data?.role === "admin" && (
            <Link
              to="/inbox"
              className="rounded-md p-2 text-muted hover:text-text"
              aria-label={t("mobile.desktopView")}
            >
              <Monitor size={18} />
            </Link>
          )}
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3">
        <Button
          variant="primary"
          size="lg"
          className="h-24 flex-col"
          onClick={() => pick("photos")}
        >
          <ImagePlus size={24} /> {t("mobile.pickPhotos")}
        </Button>
        <Button
          variant="secondary"
          size="lg"
          className="h-24 flex-col"
          onClick={() => pick("files")}
        >
          <FolderOpen size={24} /> {t("mobile.pickFiles")}
        </Button>
        <p className="col-span-2 text-xs text-muted">{t("mobile.pickHint")}</p>
      </section>

      <section className="space-y-3 rounded-xl border border-border bg-panel p-4">
        <h2 className="text-sm font-semibold">{t("mobile.metaTitle")}</h2>
        <p className="text-xs text-muted">{t("mobile.metaHint")}</p>
        <TagPicker value={tags} onChange={setTags} />
        {manualCollections.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {manualCollections.map((collection) => {
              const checked = collectionIds.includes(collection.id);
              return (
                <button
                  key={collection.id}
                  type="button"
                  aria-pressed={checked}
                  onClick={() =>
                    setCollectionIds(
                      checked
                        ? collectionIds.filter((id) => id !== collection.id)
                        : [...collectionIds, collection.id],
                    )
                  }
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs",
                    checked ? "border-accent bg-accent/15 text-accent" : "border-border text-muted",
                  )}
                >
                  {collection.name}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-muted">{t("mobile.noCollections")}</p>
        )}
        <button
          type="button"
          aria-pressed={favorite}
          onClick={() => setFavorite(!favorite)}
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
            favorite ? "border-danger/50 text-danger" : "border-border text-muted",
          )}
        >
          <Heart size={16} fill={favorite ? "currentColor" : "none"} /> {t("mobile.favorite")}
        </button>
      </section>

      {items.length > 0 && (
        <section className="rounded-xl border border-border bg-panel">
          <header className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-medium">
              {summary.active > 0
                ? t("upload.trayActive", { count: summary.active })
                : t("upload.trayDone", { done: summary.done, duplicate: summary.duplicate })}
            </span>
            {summary.active === 0 && (
              <Button size="sm" variant="ghost" onClick={clearFinished}>
                {t("upload.clear")}
              </Button>
            )}
          </header>
          {summary.active > 0 && (
            <p className="border-b border-border px-3 py-2 text-xs text-warning">
              {t("mobile.keepScreenOn")}
            </p>
          )}
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <UploadRow key={item.id} item={item} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
