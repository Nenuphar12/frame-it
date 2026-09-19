// Artwork metadata while editing: title, tags (inherited from the photos and pre-checked), the
// favourite flag and the snapshots — including "revert to when opened" (§11.1, §14 phase 5.7).
import { Heart, History } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Artwork, Photo } from "@/api/client";
import { useArtworkActions, useRestoreSnapshot, useSnapshots } from "@/api/queries";
import { TagPicker } from "@/features/tags/TagPicker";
import { Button } from "@/shared/ui/Button";
import { PanelSection } from "./Controls";

interface InfoSheetProps {
  artwork: Artwork;
  photos: Photo[];
  openedSnapshotId: string | null;
}

export function InfoSheet({ artwork, photos, openedSnapshotId }: InfoSheetProps) {
  const { t } = useTranslation();
  const { update } = useArtworkActions();
  const snapshots = useSnapshots(artwork.id);
  const restore = useRestoreSnapshot();
  // A draft over the stored title: no effect is needed to follow the server's value.
  const [draft, setDraft] = useState<string | null>(null);
  const title = draft ?? artwork.title;

  // Tags of the photos the artwork is made of: the obvious suggestions when tagging it.
  const tags = artwork.tags ?? [];
  const suggested = photos
    .flatMap((photo) => photo.tags ?? [])
    .filter(
      (tag, index, all) =>
        all.findIndex((other) => other.id === tag.id) === index &&
        !tags.some((existing) => existing.id === tag.id),
    );

  const setTags = (tags: { id: string }[]) =>
    update.mutate({ id: artwork.id, tag_ids: tags.map((tag) => tag.id) });

  return (
    <>
      <PanelSection title={t("editor.sections.artwork")}>
        <input
          value={title}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            if (title !== artwork.title) update.mutate({ id: artwork.id, title });
            setDraft(null);
          }}
          placeholder={t("artworks.untitled")}
          aria-label={t("editor.info.title")}
          className="h-7 w-full rounded border border-border bg-panel-2 px-1.5 text-xs"
        />
        <Button
          size="sm"
          variant={artwork.favorite ? "primary" : "secondary"}
          onClick={() => update.mutate({ id: artwork.id, favorite: !artwork.favorite })}
        >
          <Heart size={13} fill={artwork.favorite ? "currentColor" : "none"} />
          {t("artworks.favorite")}
        </Button>
      </PanelSection>

      <PanelSection title={t("editor.sections.tags")}>
        <TagPicker value={tags} onChange={setTags} />
        {suggested.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] text-muted">{t("editor.info.fromPhotos")}</span>
            {suggested.map((tag) => (
              <button
                key={tag.id}
                type="button"
                onClick={() => setTags([...tags, tag])}
                className="rounded border border-dashed border-border px-1.5 py-px text-[11px] text-muted hover:text-text"
              >
                + {tag.name}
              </button>
            ))}
          </div>
        )}
      </PanelSection>

      <PanelSection title={t("editor.sections.history")}>
        {openedSnapshotId && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              restore.mutate({ artworkId: artwork.id, snapshotId: openedSnapshotId })
            }
          >
            <History size={13} /> {t("editor.history.revertToOpened")}
          </Button>
        )}
        <ul className="flex flex-col gap-1 text-[11px] text-muted">
          {(snapshots.data ?? []).slice(0, 5).map((snapshot) => (
            <li key={snapshot.id} className="flex items-center gap-2">
              <span className="flex-1 truncate">
                {t(`editor.history.reasons.${snapshot.reason}`, {
                  defaultValue: snapshot.reason,
                })}{" "}
                · v{snapshot.document_version}
              </span>
              <button
                type="button"
                className="hover:text-text"
                onClick={() =>
                  restore.mutate({ artworkId: artwork.id, snapshotId: snapshot.id })
                }
              >
                {t("editor.history.restore")}
              </button>
            </li>
          ))}
        </ul>
      </PanelSection>
    </>
  );
}
