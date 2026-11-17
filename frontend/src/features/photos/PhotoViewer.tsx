import * as RadixDialog from "@radix-ui/react-dialog";
import {
  AlertTriangle,
  Archive,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
} from "react";
import { useTranslation } from "react-i18next";

import { photoOriginalUrl, photoProxyUrl, photoThumbUrl, type Photo } from "@/api/client";
import { useRegisterCommands, type Command } from "@/app/commands";
import { cn } from "@/shared/cn";
import { formatCaptureTime, megapixels } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Badge, Kbd, Spinner } from "@/shared/ui/Misc";

import { coversTv } from "./quality";

/** Room left around a fitted photo (CSS px, each side). */
const FIT_MARGIN = 16;
/** A press that moves less than this (CSS px) is a click, not a pan. */
const DRAG_THRESHOLD = 4;

interface PhotoViewerProps {
  photoId: string;
  /** The grid's photos, in its order: the arrows walk them. */
  photos: Photo[];
  selected: ReadonlySet<string>;
  onToggleSelected: (id: string) => void;
  onNavigate: (id: string) => void;
  onClose: () => void;
  /** Move the photo to the trash; the page moves the viewer on once it is gone. */
  onTrash: (id: string) => void;
  /** The Inbox: take the photo off the list, keep it in the library. */
  onDismiss?: (id: string) => void;
  /** Near the end of what is loaded: fetch the next page. */
  onEndReached?: () => void;
  /** A dialog of the page is open over the viewer (the trash cascade): the keys stand down. */
  suspended?: boolean;
}

/** Where a zoom should keep a point of the photo: at ratio (rx, ry) of it, under (px, py) of the view. */
interface ZoomAnchor {
  rx: number;
  ry: number;
  px: number;
  py: number;
}

function place(photo: Photo): string | null {
  const parts = [photo.place_name, photo.place_country].filter(Boolean);
  return parts.length ? [...new Set(parts)].join(", ") : null;
}

/**
 * A photo full screen, to sort a burst: which one to keep, which ones to trash (user feedback).
 *
 * Fitted, it shows the proxy (the thumbnail stands in while it loads); `z` or a click shows the
 * original at 100% (one photo pixel per screen pixel) around the point clicked, panned by
 * dragging or scrolling. The zoom stays on, at the same spot, from one photo to the next: that is
 * how two shots of a burst compare for sharpness. `s` adds the photo to the grid's selection,
 * `Delete` trashes it (Undo in the toast) and shows the next one.
 */
export function PhotoViewer({
  photoId,
  photos,
  selected,
  onToggleSelected,
  onNavigate,
  onClose,
  onTrash,
  onDismiss,
  onEndReached,
  suspended = false,
}: PhotoViewerProps) {
  const { t } = useTranslation();
  const index = photos.findIndex((p) => p.id === photoId);
  const photo = photos[index];
  const isSelected = selected.has(photoId);

  const contentRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [area, setArea] = useState<{ width: number; height: number } | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [loaded, setLoaded] = useState<ReadonlySet<string>>(new Set());
  /** Where the next zoom-in keeps the photo (the point clicked); `null` = the view's centre. */
  const anchorRef = useRef<ZoomAnchor | null>(null);
  /** The point of the photo at the view's centre while zoomed: the next photo opens there. */
  const centreRef = useRef({ rx: 0.5, ry: 0.5 });
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const movedRef = useRef(false);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setArea({ width: entry!.contentRect.width, height: entry!.contentRect.height }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (index >= photos.length - 3) onEndReached?.();
  }, [index, photos.length, onEndReached]);

  // The neighbours' proxies, fetched ahead: the arrows then switch at once.
  const previousId = photos[index - 1]?.id;
  const nextId = photos[index + 1]?.id;
  useEffect(() => {
    for (const id of [nextId, previousId]) {
      if (id) new Image().src = photoProxyUrl(id);
    }
  }, [nextId, previousId]);

  const dpr = window.devicePixelRatio || 1;
  /** 100%: one photo pixel per device pixel. */
  const actualScale = 1 / dpr;
  const fitScale =
    area && photo
      ? Math.min(
          (area.width - 2 * FIT_MARGIN) / photo.width,
          (area.height - 2 * FIT_MARGIN) / photo.height,
          actualScale, // a small photo is not blown up: fitted, it is already at 100%
        )
      : 0;
  const canZoom = fitScale > 0 && fitScale < actualScale * 0.98;
  const isZoomed = zoomed && canZoom;
  const scale = isZoomed ? actualScale : fitScale;
  const boxWidth = photo ? Math.round(photo.width * scale) : 0;
  const boxHeight = photo ? Math.round(photo.height * scale) : 0;

  // Zoomed in (or on to another photo while zoomed): put the anchored point where it belongs.
  useLayoutEffect(() => {
    const element = scrollRef.current;
    const box = boxRef.current;
    if (!element || !box || !isZoomed) return;
    const anchor = anchorRef.current ?? {
      ...centreRef.current,
      px: element.clientWidth / 2,
      py: element.clientHeight / 2,
    };
    anchorRef.current = null;
    element.scrollLeft = box.offsetLeft + anchor.rx * boxWidth - anchor.px;
    element.scrollTop = box.offsetTop + anchor.ry * boxHeight - anchor.py;
  }, [photoId, isZoomed, boxWidth, boxHeight]);

  const zoomTo = useCallback((next: boolean, anchor: ZoomAnchor | null = null) => {
    anchorRef.current = anchor;
    if (!next) centreRef.current = { rx: 0.5, ry: 0.5 }; // the next zoom starts at the centre
    setZoomed(next);
  }, []);

  const go = useCallback(
    (delta: number) => {
      const next = photos[index + delta];
      if (next) onNavigate(next.id);
    },
    [index, onNavigate, photos],
  );

  const group = "commands.groups.photoViewer";
  const commands = useMemo<Command[]>(
    () => [
      {
        id: "photoViewer.next",
        label: "photos.viewer.next",
        group,
        shortcut: "ArrowRight",
        run: () => go(1),
      },
      {
        id: "photoViewer.previous",
        label: "photos.viewer.previous",
        group,
        shortcut: "ArrowLeft",
        run: () => go(-1),
      },
      {
        id: "photoViewer.select",
        label: "photos.viewer.toggleSelect",
        group,
        shortcut: "s",
        run: () => onToggleSelected(photoId),
      },
      {
        id: "photoViewer.zoom",
        label: "photos.viewer.toggleZoom",
        group,
        shortcut: "z",
        run: () => {
          if (canZoom) zoomTo(!isZoomed);
        },
      },
      {
        id: "photoViewer.trash",
        label: "trash.moveToTrash",
        group,
        shortcut: "Delete",
        run: () => onTrash(photoId),
      },
      ...(onDismiss
        ? [
            {
              id: "photoViewer.dismiss",
              label: "inbox.dismiss",
              group,
              shortcut: "d",
              run: () => onDismiss(photoId),
            },
          ]
        : []),
    ],
    [canZoom, go, isZoomed, onDismiss, onToggleSelected, onTrash, photoId, zoomTo],
  );
  useRegisterCommands(suspended ? [] : commands);

  // Panning: the scroll position is written straight to the element, never through React state
  // (one render per pointer event would outrun the browser, AGENTS.md invariant 12).
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    movedRef.current = false;
    const element = scrollRef.current;
    // A finger or a pen scrolls natively; only the mouse needs dragging by hand.
    if (!isZoomed || !element || event.pointerType !== "mouse" || event.button !== 0) return;
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      left: element.scrollLeft,
      top: element.scrollTop,
    };
    element.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const element = scrollRef.current;
    if (!drag || !element) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!movedRef.current && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    movedRef.current = true;
    element.scrollLeft = drag.left - dx;
    element.scrollTop = drag.top - dy;
  };
  const endDrag = () => {
    dragRef.current = null;
  };
  const onScroll = () => {
    const element = scrollRef.current;
    const box = boxRef.current;
    if (!element || !box || !isZoomed) return;
    centreRef.current = {
      rx: (element.scrollLeft + element.clientWidth / 2 - box.offsetLeft) / boxWidth,
      ry: (element.scrollTop + element.clientHeight / 2 - box.offsetTop) / boxHeight,
    };
  };
  /** A click (not the end of a pan): zoomed, back to fit; fitted, 100% around the point. */
  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    if (movedRef.current) return;
    if (isZoomed) {
      zoomTo(false);
      return;
    }
    const box = boxRef.current?.getBoundingClientRect();
    const view = scrollRef.current?.getBoundingClientRect();
    if (!canZoom || !box || !view) return;
    const inside =
      event.clientX >= box.left &&
      event.clientX <= box.right &&
      event.clientY >= box.top &&
      event.clientY <= box.bottom;
    if (!inside) return;
    zoomTo(true, {
      rx: (event.clientX - box.left) / box.width,
      ry: (event.clientY - box.top) / box.height,
      px: event.clientX - view.left,
      py: event.clientY - view.top,
    });
  };

  const markLoaded = (src: string) =>
    setLoaded((current) => (current.has(src) ? current : new Set(current).add(src)));
  const proxy = photoProxyUrl(photoId);
  const original = photoOriginalUrl(photoId);
  const waiting = photo !== undefined && !loaded.has(isZoomed ? original : proxy);
  const details = photo
    ? [
        megapixels(photo.width, photo.height),
        photo.taken_at ? formatCaptureTime(photo.taken_at) : null,
        place(photo),
        [photo.camera_make, photo.camera_model].filter(Boolean).join(" ") || null,
      ].filter(Boolean)
    : [];

  return (
    <RadixDialog.Root open onOpenChange={(open) => !open && onClose()}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/90" />
        <RadixDialog.Content
          ref={contentRef}
          // The keys act on the photo: no button takes the focus (a focused button would answer
          // Enter and Space itself).
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            contentRef.current?.focus();
          }}
          // Back in the grid, the keyboard is on the photo last shown (`PhotoGrid` scrolled to it).
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            document
              .querySelector<HTMLElement>(`[data-photo-id="${CSS.escape(photoId)}"]`)
              ?.focus({ preventScroll: true });
          }}
          onEscapeKeyDown={(event) => {
            event.stopPropagation(); // `Escape` only closes the viewer (see `shared/ui/Dialog`)
            if (isZoomed) {
              event.preventDefault(); // zoomed, the first `Escape` goes back to fit
              zoomTo(false);
            }
          }}
          className="fixed inset-0 z-50 flex flex-col outline-none"
        >
          <RadixDialog.Title className="sr-only">
            {photo?.original_filename ?? t("photos.details")}
          </RadixDialog.Title>
          <RadixDialog.Description className="sr-only">
            {t("photos.viewer.hint")}
          </RadixDialog.Description>
          <div className="relative min-h-0 flex-1">
            <div
              ref={scrollRef}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onScroll={onScroll}
              onClick={onClick}
              className={cn(
                "absolute inset-0 overflow-auto select-none [scrollbar-width:none]",
                isZoomed && "cursor-grab active:cursor-grabbing",
              )}
            >
              {/* Auto margins centre the photo yet never push it past the scrollable edge. */}
              <div className="relative flex min-h-full w-max min-w-full">
                {photo && boxWidth > 0 && (
                  <div
                    ref={boxRef}
                    className={cn(
                      "relative m-auto shrink-0",
                      canZoom && !isZoomed && "cursor-zoom-in",
                    )}
                    style={{ width: boxWidth, height: boxHeight }}
                  >
                    {/* Stacked, each covering the one below once it has loaded (the dialog's title names
                        the photo, so they are all decorative). */}
                    <img
                      key={`thumb-${photoId}`}
                      src={photoThumbUrl(photoId, 768)}
                      alt=""
                      draggable={false}
                      className="absolute inset-0 h-full w-full"
                    />
                    <img
                      key={proxy}
                      src={proxy}
                      alt=""
                      draggable={false}
                      onLoad={() => markLoaded(proxy)}
                      onError={() => markLoaded(proxy)}
                      className="absolute inset-0 h-full w-full"
                    />
                    {isZoomed && (
                      <img
                        key={original}
                        src={original}
                        alt=""
                        draggable={false}
                        onLoad={() => markLoaded(original)}
                        // Failed: the proxy stays visible, the spinner must not spin forever.
                        onError={() => markLoaded(original)}
                        className="absolute inset-0 h-full w-full"
                      />
                    )}
                  </div>
                )}
              </div>
            </div>
            {isSelected && (
              <span className="pointer-events-none absolute top-4 left-4 inline-flex items-center gap-1 rounded-full bg-accent px-2.5 py-1 text-xs font-medium text-accent-contrast shadow">
                <Check size={13} strokeWidth={3} /> {t("photos.viewer.selected")}
              </span>
            )}
            {waiting && (
              <div className="pointer-events-none absolute top-4 right-4">
                <Spinner size={18} />
              </div>
            )}
            <button
              type="button"
              className="absolute top-1/2 left-2 -translate-y-1/2 rounded-full p-2 text-white/70 hover:bg-white/10 disabled:opacity-20"
              onClick={() => go(-1)}
              disabled={index <= 0}
              aria-label={t("photos.viewer.previous")}
            >
              <ChevronLeft size={28} />
            </button>
            <button
              type="button"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-2 text-white/70 hover:bg-white/10 disabled:opacity-20"
              onClick={() => go(1)}
              disabled={index < 0 || index >= photos.length - 1}
              aria-label={t("photos.viewer.next")}
            >
              <ChevronRight size={28} />
            </button>
          </div>
          {photo && (
            <div className="flex flex-wrap items-center gap-2 border-t border-white/10 bg-panel px-4 py-2.5">
              <div className="mr-auto flex min-w-0 flex-wrap items-center gap-2">
                <span className="text-xs text-muted tabular-nums">
                  {t("photos.viewer.position", { index: index + 1, total: photos.length })}
                </span>
                <span className="truncate text-sm font-medium">{photo.original_filename}</span>
                {coversTv(photo) ? (
                  <Badge tone="accent" title={t("photos.coversTvHint")}>
                    4K+
                  </Badge>
                ) : (
                  <Badge tone="neutral" title={t("photos.belowTvHint")}>
                    {photo.width}×{photo.height}
                  </Badge>
                )}
                {photo.quality_warnings.length > 0 && (
                  <Badge
                    tone="warning"
                    title={photo.quality_warnings.map((w) => t(`photos.warnings.${w}`)).join("\n")}
                  >
                    <AlertTriangle size={11} />
                  </Badge>
                )}
                <span className="text-xs text-muted">{details.join(" · ")}</span>
              </div>
              <Button
                size="sm"
                variant={isSelected ? "primary" : "secondary"}
                aria-pressed={isSelected}
                onClick={() => onToggleSelected(photoId)}
                title={t("photos.viewer.selectHint")}
              >
                <Check size={14} />
                {isSelected ? t("photos.viewer.selected") : t("photos.viewer.select")} <Kbd>S</Kbd>
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={!canZoom}
                aria-pressed={isZoomed}
                onClick={() => zoomTo(!isZoomed)}
                title={t("photos.viewer.zoomHint")}
              >
                {isZoomed ? <ZoomOut size={14} /> : <ZoomIn size={14} />}
                {isZoomed ? t("photos.viewer.fit") : t("photos.viewer.actualSize")} <Kbd>Z</Kbd>
              </Button>
              {onDismiss && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onDismiss(photoId)}
                  title={t("inbox.dismissHint")}
                >
                  <Archive size={14} /> {t("inbox.dismiss")} <Kbd>D</Kbd>
                </Button>
              )}
              <Button size="sm" variant="ghost" asChild>
                <a
                  href={original}
                  download={photo.original_filename}
                  aria-label={t("photos.downloadOriginal")}
                  title={t("photos.downloadOriginal")}
                >
                  <Download size={14} />
                </a>
              </Button>
              <Button size="sm" variant="danger" onClick={() => onTrash(photoId)}>
                <Trash2 size={14} /> {t("trash.moveToTrash")}
              </Button>
              <RadixDialog.Close
                className="rounded p-1.5 text-muted hover:bg-panel-2 hover:text-text"
                aria-label={t("common.close")}
              >
                <X size={16} />
              </RadixDialog.Close>
            </div>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
