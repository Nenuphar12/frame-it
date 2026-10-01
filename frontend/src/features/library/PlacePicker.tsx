import { MapPin } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import type { PlaceMatch } from "@/api/client";
import { usePlaceSearch } from "@/api/queries";
import { cn } from "@/shared/cn";

import type { NearValue } from "./filters";

interface PlacePickerProps {
  value: NearValue;
  onChange: (value: NearValue) => void;
  className?: string;
}

/** How long typing has to pause before the picker asks the server. */
const DEBOUNCE_MS = 200;

function useDebounced(text: string): string {
  const [settled, setSettled] = useState(text);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [text]);
  return settled;
}

function placeLabel(place: PlaceMatch): string {
  return [place.name, place.country].filter(Boolean).join(", ");
}

/**
 * The point of a `place near` clause, picked by name from the offline dataset
 * (`GET /places/search`: accents ignored, `"paris, texas"` narrows, the library's places first).
 *
 * Typing again after a pick drops the point — the chip then stops filtering until a place is
 * picked — so the bar never filters on a place its text no longer names.
 */
export function PlacePicker({ value, onChange, className }: PlacePickerProps) {
  const { t } = useTranslation();
  const listId = useId();
  const [text, setText] = useState(value.label);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const term = useDebounced(text.trim());
  const picked = value.lat !== undefined && text === value.label;
  const results = usePlaceSearch(open && !picked ? term : "");
  const places = results.data ?? [];
  const showList = open && !picked && term.length > 0;

  const pick = (place: PlaceMatch) => {
    const label = placeLabel(place);
    setText(label);
    setOpen(false);
    onChange({ ...value, lat: place.lat, lon: place.lon, label });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!showList || places.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % places.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + places.length) % places.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const place = places[active];
      if (place) pick(place);
    }
  };

  return (
    <span className={cn("relative inline-flex items-center", className)}>
      <MapPin size={12} className="pointer-events-none absolute left-1.5 text-muted" />
      <input
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={t("filters.nearPlace")}
        value={text}
        placeholder={t("filters.nearPlaceholder")}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        onChange={(event) => {
          setText(event.target.value);
          setActive(0);
          setOpen(true);
          // The text no longer names the picked point: forget it until another place is picked.
          if (value.lat !== undefined) onChange({ km: value.km, label: event.target.value });
        }}
        className="h-7 w-44 rounded border border-border bg-bg pr-1.5 pl-5 text-xs outline-none focus:border-accent"
      />
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute top-full left-0 z-50 mt-1 max-h-64 w-72 overflow-y-auto rounded-md border border-border bg-panel p-1 shadow-xl"
        >
          {places.length === 0 ? (
            <li className="px-2 py-1.5 text-xs text-muted">
              {results.isFetching ? t("filters.nearSearching") : t("filters.nearNoMatch")}
            </li>
          ) : (
            places.map((place, index) => (
              <li
                key={`${place.name}|${place.admin1}|${place.country}|${place.lat}|${place.lon}`}
                role="option"
                aria-selected={index === active}
                // `mousedown`, not `click`: the input's blur would close the list first.
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(place);
                }}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "flex cursor-pointer items-baseline gap-2 rounded px-2 py-1.5 text-xs",
                  index === active && "bg-panel-2",
                )}
              >
                <span className="font-medium">{place.name}</span>
                <span className="min-w-0 flex-1 truncate text-muted">
                  {[place.admin1, place.country].filter(Boolean).join(", ")}
                </span>
                {place.photo_count > 0 && (
                  <span className="shrink-0 text-accent">
                    {t("photos.count", { count: place.photo_count })}
                  </span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </span>
  );
}
