import { AlertTriangle, Heart } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ArtworkSummary } from "@/api/client";
import { Badge } from "@/shared/ui/Misc";

/** Quality tier (with the worst scale when resampled), draft/ready, incomplete, favourite. */
export function ArtworkBadges({ artwork }: { artwork: ArtworkSummary }) {
  const { t } = useTranslation();
  const tier = artwork.worst_tier;
  const percent = artwork.max_scale !== null ? Math.round(artwork.max_scale * 100) : null;
  return (
    <>
      {tier && (
        <Badge
          tone={tier === "native" ? "accent" : tier === "upscaled" ? "warning" : "neutral"}
          title={t(`artworks.tierHints.${tier}`)}
        >
          {t(`artworks.tiers.${tier}`)}
          {tier === "upscaled" && percent !== null && ` ${percent}%`}
        </Badge>
      )}
      <Badge tone={artwork.status === "ready" ? "info" : "neutral"}>
        {t(`artworks.statuses.${artwork.status}`)}
      </Badge>
      {artwork.is_incomplete && (
        <Badge tone="warning" title={t("artworks.incompleteHint")}>
          <AlertTriangle size={11} />
        </Badge>
      )}
      {artwork.favorite && (
        <Badge tone="danger" title={t("artworks.favorite")}>
          <Heart size={11} fill="currentColor" />
        </Badge>
      )}
    </>
  );
}
