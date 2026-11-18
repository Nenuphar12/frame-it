import { Link } from "@tanstack/react-router";
import { CalendarDays, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineMonth, TimelineYear } from "@/api/client";
import { useTimeline } from "@/api/queries";
import { formatMonth } from "@/shared/format";
import { periodOf } from "@/shared/period";
import { EmptyState, Spinner } from "@/shared/ui/Misc";

/**
 * When the photos were taken — year → month — read from their capture time, the Places view's
 * twin (docs/organization.md §1). Each row opens the photo grid filtered to that period
 * (`/photos?taken=`) and the artworks made of a photo from then (`/artworks?taken=`, the
 * `taken_at` "between" chip). A photo without a capture date is counted apart.
 */
export function TimelineView() {
  const { t } = useTranslation();
  const timeline = useTimeline();
  if (timeline.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={20} />
      </div>
    );
  }
  const years = timeline.data?.years ?? [];
  const undated = timeline.data?.undated_photos ?? 0;
  return (
    <div className="space-y-3">
      {years.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={40} />}
          title={t("timeline.emptyTitle")}
          description={t("timeline.emptyDescription")}
        />
      ) : (
        <ul className="space-y-1" aria-label={t("timeline.title")}>
          {years.map((year, index) => (
            // The latest year starts open; the others closed (a library can span decades).
            <YearRow key={year.year} year={year} initiallyOpen={index === 0} />
          ))}
        </ul>
      )}
      {undated > 0 && (
        <p className="text-xs text-muted">{t("timeline.undated", { count: undated })}</p>
      )}
    </div>
  );
}

function YearRow({ year, initiallyOpen }: { year: TimelineYear; initiallyOpen: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(initiallyOpen);
  const label = String(year.year);
  return (
    <li>
      <div className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-panel-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={t(open ? "timeline.collapse" : "timeline.expand", { year: label })}
          className="rounded text-muted hover:text-text"
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span className="min-w-0 flex-1 truncate font-medium tabular-nums">{label}</span>
        <Counts period={periodOf(year.year)} counts={year} />
      </div>
      {open && (
        <ul>
          {year.months.map((month) => (
            <MonthRow key={month.month} year={year.year} month={month} />
          ))}
        </ul>
      )}
    </li>
  );
}

function MonthRow({ year, month }: { year: number; month: TimelineMonth }) {
  return (
    <li
      className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-panel-2"
      style={{ paddingLeft: "1.5rem" }}
    >
      <span className="w-3.5" />
      <span className="min-w-0 flex-1 truncate">{formatMonth(month.month)}</span>
      <Counts period={periodOf(year, month.month)} counts={month} />
    </li>
  );
}

const LINK = "text-right text-xs text-accent tabular-nums hover:underline";

function Counts({
  period,
  counts,
}: {
  period: string;
  counts: { photo_count: number; artwork_count: number };
}) {
  const { t } = useTranslation();
  return (
    <>
      <Link to="/photos" search={{ taken: period }} className={`w-24 ${LINK}`}>
        {t("places.photoCount", { count: counts.photo_count })}
      </Link>
      {counts.artwork_count > 0 ? (
        <Link to="/artworks" search={{ taken: period }} className={`w-28 ${LINK}`}>
          {t("places.artworkCount", { count: counts.artwork_count })}
        </Link>
      ) : (
        <span className="w-28 text-right text-xs text-muted tabular-nums">
          {t("places.artworkCount", { count: 0 })}
        </span>
      )}
    </>
  );
}
