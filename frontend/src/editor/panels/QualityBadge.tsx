// Live quality of the selected slot and of the whole artwork (§7.2): the badge the whole editor
// is built around — it must stay correct while dragging, so it is computed from the working
// document, never from the server's derived columns.
import { useTranslation } from "react-i18next";

import type { EditorDocument } from "@/editor/core/document.ts";
import { artworkQuality, slotQuality, type SlotGeometry } from "@/editor/core/quality.ts";
import { Badge } from "@/shared/ui/Misc";

const geometry = (slot: EditorDocument["slots"][number]): SlotGeometry => ({
  rect_w: slot.rect.w,
  rect_h: slot.rect.h,
  crop_w: slot.source.crop.w,
  crop_h: slot.source.crop.h,
  rotation: slot.rotation,
  has_photo: slot.photo_id !== null,
});

const tone = (tier: string) =>
  tier === "native" ? "accent" : tier === "upscaled" ? "warning" : "neutral";

export function SlotQualityBadge({ slot }: { slot: EditorDocument["slots"][number] }) {
  const { t } = useTranslation();
  if (!slot.photo_id) return <Badge tone="warning">{t("editor.quality.empty")}</Badge>;
  const quality = slotQuality(geometry(slot));
  return (
    <Badge tone={tone(quality.tier)} title={t(`artworks.tierHints.${quality.tier}`)}>
      {t(`artworks.tiers.${quality.tier}`)} {quality.percent}%
    </Badge>
  );
}

export function DocumentQualityBadge({ doc }: { doc: EditorDocument }) {
  const { t } = useTranslation();
  const quality = artworkQuality(doc.slots.map(geometry));
  if (quality.worst_tier === null) {
    return <Badge tone="warning">{t("editor.quality.empty")}</Badge>;
  }
  const percent = Math.round((quality.max_scale ?? 1) * 100);
  return (
    <>
      <Badge tone={tone(quality.worst_tier)} title={t(`artworks.tierHints.${quality.worst_tier}`)}>
        {t(`artworks.tiers.${quality.worst_tier}`)} {percent}%
      </Badge>
      {quality.is_incomplete && <Badge tone="warning">{t("artworks.incompleteHint")}</Badge>}
    </>
  );
}
