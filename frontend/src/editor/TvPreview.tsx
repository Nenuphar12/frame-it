// TV preview (§11.2): the **server render** shown full screen, scaled to fit the monitor, with a
// simulated bezel and an optional matte overlay — how the artwork will actually look on the wall.
// Uses the Fullscreen API, which works over plain HTTP (invariant 8).
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkRenderUrl, artworkThumbUrl, type ArtworkSummary } from "@/api/client";
import { cn } from "@/shared/cn";
import { Spinner } from "@/shared/ui/Misc";

const BEZELS = ["#161616", "#5A4A3A", "#D8D3C8"] as const;

interface TvPreviewProps {
  artwork: ArtworkSummary;
  /** Artworks to walk through with ←/→ (the current list); optional. */
  ids?: string[];
  onNavigate?: (id: string) => void;
  onClose: () => void;
}

export function TvPreview({ artwork, ids = [], onNavigate, onClose }: TvPreviewProps) {
  const { t } = useTranslation();
  const root = useRef<HTMLDivElement>(null);
  const [bezel, setBezel] = useState(0);
  const [matte, setMatte] = useState(false);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const index = ids.indexOf(artwork.id);
  const src = artworkRenderUrl(artwork, "jpg");
  const loaded = loadedSrc === src;
  // The latest `onClose`, read by the effects below instead of being one of their dependencies.
  // Callers pass an inline arrow, i.e. a new function on every render of the editor (autosave, a
  // fresh render arriving over SSE…). As a dependency it re-ran the fullscreen effect: its cleanup
  // left fullscreen, and the re-run's `fullscreenchange` listener read that as the user leaving and
  // closed the preview — it opened, flickered and shut (remarks.md #4).
  const closeRef = useRef(onClose);
  useLayoutEffect(() => {
    closeRef.current = onClose;
  });

  const go = useCallback(
    (delta: number) => {
      const next = ids[index + delta];
      if (next && onNavigate) onNavigate(next);
    },
    [ids, index, onNavigate],
  );

  // Fullscreen for as long as the preview is mounted — once, whatever the parent re-renders.
  useEffect(() => {
    const element = root.current;
    if (element && !document.fullscreenElement) {
      void element.requestFullscreen?.().catch(() => undefined);
    }
    const onChange = () => {
      if (!document.fullscreenElement) closeRef.current();
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") go(1);
      else if (event.key === "ArrowLeft") go(-1);
      else if (event.key === "b") setBezel((value) => (value + 1) % BEZELS.length);
      else if (event.key === "m") setMatte((value) => !value);
      else if (event.key === "Escape") closeRef.current();
      else return;
      event.preventDefault();
      // Captured before the command registry sees it: `Escape` closes the preview, it does not
      // also leave the editor underneath.
      event.stopPropagation();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [go]);

  return (
    <div ref={root} className="fixed inset-0 z-[60] flex items-center justify-center bg-black">
      <div
        className="relative max-h-full max-w-full"
        style={{
          aspectRatio: "16 / 9",
          width: "min(100vw, calc(100vh * 16 / 9))",
          padding: "min(1.6vw, 22px)",
          backgroundColor: BEZELS[bezel],
          boxShadow: "0 0 60px rgba(0,0,0,0.9)",
        }}
      >
        <div className="relative h-full w-full overflow-hidden bg-black">
          <img
            src={artworkThumbUrl(artwork, 768)}
            alt=""
            className={cn("absolute inset-0 h-full w-full object-cover", loaded && "invisible")}
          />
          <img
            src={src}
            alt={artwork.title}
            onLoad={() => setLoadedSrc(src)}
            className="relative h-full w-full object-cover"
          />
          {matte && (
            <div
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse at 50% 40%, rgba(255,255,255,0.05), rgba(0,0,0,0.20) 90%)",
                mixBlendMode: "multiply",
              }}
            />
          )}
          {!loaded && (
            <div className="absolute top-4 right-4">
              <Spinner size={18} />
            </div>
          )}
        </div>
      </div>

      <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white/80 opacity-30 backdrop-blur transition hover:opacity-100">
        {ids.length > 1 && (
          <>
            <button type="button" aria-label={t("artworks.previous")} onClick={() => go(-1)}>
              <ChevronLeft size={16} />
            </button>
            <span className="tabular-nums">
              {index + 1} / {ids.length}
            </span>
            <button type="button" aria-label={t("artworks.next")} onClick={() => go(1)}>
              <ChevronRight size={16} />
            </button>
          </>
        )}
        <button type="button" onClick={() => setBezel((value) => (value + 1) % BEZELS.length)}>
          {t("editor.tv.bezel")}
        </button>
        <button type="button" aria-pressed={matte} onClick={() => setMatte((value) => !value)}>
          {t("editor.tv.matte")}
        </button>
        <button type="button" aria-label={t("common.close")} onClick={onClose}>
          <X size={16} />
        </button>
      </div>
    </div>
  );
}
