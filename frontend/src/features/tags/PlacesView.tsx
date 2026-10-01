import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, MapPin } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlaceNode } from "@/api/client";
import { usePlaces } from "@/api/queries";
import { EmptyState, Spinner } from "@/shared/ui/Misc";

/**
 * Where the photos were taken — country → region → place — read from their metadata, never
 * typed (docs/organization.md §1). This is why there is no "Places" tag category: the offline
 * geocoder already knows, and a tag would only drift from it. Each row opens the artworks made
 * of a photo from there (the `place` filter, "contains", over name, region and country).
 */
export function PlacesView() {
  const { t } = useTranslation();
  const places = usePlaces();
  if (places.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={20} />
      </div>
    );
  }
  const countries = places.data?.countries ?? [];
  const unplaced = places.data?.unplaced_photos ?? 0;
  return (
    <div className="space-y-3">
      {countries.length === 0 ? (
        <EmptyState
          icon={<MapPin size={40} />}
          title={t("places.emptyTitle")}
          description={t("places.emptyDescription")}
        />
      ) : (
        <ul className="space-y-1" aria-label={t("places.title")}>
          {countries.map((country) => (
            <PlaceRow key={country.name} place={country} depth={0} />
          ))}
        </ul>
      )}
      {unplaced > 0 && (
        <p className="text-xs text-muted">{t("places.unplaced", { count: unplaced })}</p>
      )}
    </div>
  );
}

function PlaceRow({ place, depth }: { place: PlaceNode; depth: number }) {
  const { t } = useTranslation();
  const children = place.children ?? [];
  // Countries start open (there are few); regions start closed (there can be many).
  const [open, setOpen] = useState(depth === 0);
  return (
    <li>
      <div
        className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-panel-2"
        style={{ paddingLeft: `${depth * 1.25 + 0.25}rem` }}
      >
        {children.length > 0 ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={t(open ? "places.collapse" : "places.expand", { name: place.name })}
            className="rounded text-muted hover:text-text"
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="w-3.5" />
        )}
        <span className="min-w-0 flex-1 truncate">{place.name || t("places.unnamed")}</span>
        <span className="text-xs text-muted tabular-nums">
          {t("places.photoCount", { count: place.photo_count })}
        </span>
        {place.artwork_count > 0 && place.name ? (
          <Link
            to="/artworks"
            search={{ place: place.name }}
            className="w-28 text-right text-xs text-accent tabular-nums hover:underline"
          >
            {t("places.artworkCount", { count: place.artwork_count })}
          </Link>
        ) : (
          <span className="w-28 text-right text-xs text-muted tabular-nums">
            {t("places.artworkCount", { count: place.artwork_count })}
          </span>
        )}
      </div>
      {open && children.length > 0 && (
        <ul>
          {children.map((child) => (
            <PlaceRow key={child.name} place={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
