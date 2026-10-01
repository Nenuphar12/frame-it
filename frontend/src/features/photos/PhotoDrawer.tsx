import { Link } from "@tanstack/react-router";
import { Download, MapPin, PencilLine, Undo2, Wand2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { photoOriginalUrl, photoProxyUrl, type Photo } from "@/api/client";
import { useInboxAction, usePhoto, useUpdatePhoto } from "@/api/queries";
import { TagPicker } from "@/features/tags/TagPicker";
import { formatBytes, formatCaptureTime, formatDateTime, megapixels } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Badge, Spinner } from "@/shared/ui/Misc";

import { coversTv } from "./quality";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 py-1 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? "—"}</dd>
    </div>
  );
}

/** "Artworks near here" from a photo: a city-sized circle, widened from the chip if need be. */
const NEAR_PHOTO_KM = 10;

function place(photo: Photo): string | null {
  const parts = [photo.place_name, photo.place_admin1, photo.place_country].filter(Boolean);
  return parts.length ? [...new Set(parts)].join(", ") : null;
}

interface PhotoDrawerProps {
  photoId: string;
  onClose: () => void;
  /** Shows a "Create artwork" action for this photo. */
  onCreateArtwork?: (photoId: string) => void;
}

export function PhotoDrawer({ photoId, onClose, onCreateArtwork }: PhotoDrawerProps) {
  const { t } = useTranslation();
  const { data: photo, isLoading } = usePhoto(photoId);
  const update = useUpdatePhoto();
  const inbox = useInboxAction();

  return (
    <aside
      className="flex h-full w-[22rem] shrink-0 flex-col border-l border-border bg-panel"
      aria-label={t("photos.details")}
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold">{t("photos.details")}</h2>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted hover:text-text"
          aria-label={t("common.close")}
        >
          <X size={16} />
        </button>
      </header>
      {isLoading || !photo ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <img
            src={photoProxyUrl(photo.id)}
            alt={photo.original_filename}
            className="max-h-64 w-full rounded bg-panel-2 object-contain"
          />
          <div className="flex flex-wrap gap-1.5">
            {coversTv(photo) ? (
              <Badge tone="accent">{t("photos.coversTv")}</Badge>
            ) : (
              <Badge tone="warning">{t("photos.belowTv")}</Badge>
            )}
            {photo.is_wide_gamut && <Badge tone="info">{t("photos.wideGamut")}</Badge>}
            {photo.has_gain_map && <Badge tone="info">{t("photos.hdrGainMap")}</Badge>}
            {photo.bit_depth > 8 && (
              <Badge>{t("photos.bitDepth", { bits: photo.bit_depth })}</Badge>
            )}
          </div>
          {photo.quality_warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border border-warning/30 bg-warning/10 p-2.5 text-xs text-warning">
              {photo.quality_warnings.map((w) => (
                <li key={w}>{t(`photos.warnings.${w}`)}</li>
              ))}
            </ul>
          )}
          <section>
            <h3 className="mb-1.5 text-[11px] text-muted uppercase">{t("photos.tags")}</h3>
            <TagPicker
              value={photo.tags ?? []}
              disabled={update.isPending}
              onChange={(tags) =>
                update.mutate({ id: photo.id, tag_ids: tags.map((tag) => tag.id) })
              }
            />
          </section>
          <dl>
            <Row label={t("photos.fields.file")}>{photo.original_filename}</Row>
            <Row label={t("photos.fields.dimensions")}>
              {photo.width} × {photo.height} ({megapixels(photo.width, photo.height)})
            </Row>
            <Row label={t("photos.fields.size")}>
              {formatBytes(photo.file_size)} · {photo.mime}
            </Row>
            <Row label={t("photos.fields.taken")}>{formatCaptureTime(photo.taken_at)}</Row>
            <Row label={t("photos.fields.place")}>
              {photo.gps_lat !== null && photo.gps_lon !== null ? (
                <span className="flex flex-wrap items-center gap-x-2">
                  {/* No place name within 50 km of the position: the position itself. */}
                  {place(photo) ?? `${photo.gps_lat.toFixed(4)}, ${photo.gps_lon.toFixed(4)}`}
                  {/* The `place near` clause, pre-filled: everything shot around here. */}
                  <Link
                    to="/artworks"
                    search={{
                      near: `${photo.gps_lat.toFixed(6)},${photo.gps_lon.toFixed(6)},${NEAR_PHOTO_KM}`,
                      label: photo.place_name ?? place(photo) ?? undefined,
                    }}
                    className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                  >
                    <MapPin size={12} /> {t("photos.artworksNearHere", { km: NEAR_PHOTO_KM })}
                  </Link>
                </span>
              ) : (
                place(photo)
              )}
            </Row>
            <Row label={t("photos.fields.camera")}>
              {[photo.camera_make, photo.camera_model].filter(Boolean).join(" ") || null}
            </Row>
            <Row label={t("photos.fields.lens")}>{photo.lens}</Row>
            <Row label={t("photos.fields.colorProfile")}>{photo.icc_description}</Row>
            <Row label={t("photos.fields.imported")}>{formatDateTime(photo.imported_at)}</Row>
            <Row label={t("photos.fields.inbox")}>
              <span className="flex flex-wrap items-center gap-2">
                {t(`photos.inboxState.${photo.inbox_state}`)}
                {/* It left the inbox when an artwork using it was marked ready (or by Dismiss):
                    sending it back is always allowed, never automatic (docs/organization.md §6). */}
                {photo.inbox_state !== "inbox" && (
                  <button
                    type="button"
                    disabled={inbox.isPending}
                    onClick={() => inbox.mutate({ ids: [photo.id], action: "restore" })}
                    className="inline-flex items-center gap-1 rounded text-xs text-accent hover:underline"
                  >
                    <Undo2 size={12} /> {t("photos.backToInbox")}
                  </button>
                )}
              </span>
            </Row>
            {(photo.draft_artwork_ids ?? []).length > 0 && (
              <Row label={t("photos.fields.drafts")}>
                <span className="flex flex-wrap gap-2">
                  {(photo.draft_artwork_ids ?? []).map((artworkId, index) => (
                    <Link
                      key={artworkId}
                      to="/editor/$artworkId"
                      params={{ artworkId }}
                      className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      <PencilLine size={12} />
                      {t("photos.openDraft", { n: index + 1 })}
                    </Link>
                  ))}
                </span>
              </Row>
            )}
          </dl>
          <div className="flex flex-wrap gap-2">
            {onCreateArtwork && (
              <Button variant="primary" size="sm" onClick={() => onCreateArtwork(photo.id)}>
                <Wand2 size={14} /> {t("photos.createArtwork")}
              </Button>
            )}
            <Button asChild variant="secondary" size="sm">
              <a href={photoOriginalUrl(photo.id)} download={photo.original_filename}>
                <Download size={14} /> {t("photos.downloadOriginal")}
              </a>
            </Button>
          </div>
        </div>
      )}
    </aside>
  );
}
