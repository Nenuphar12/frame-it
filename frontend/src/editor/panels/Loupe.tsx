// Loupe (§11.4): the server renders a 512×512 TV-pixel region of the *working* document and it is
// displayed at 1 TV pixel = 1 device pixel. The only way to judge sharpness honestly — the canvas
// preview resamples proxies, the server is authoritative.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { renderRegion } from "@/api/client";
import { toApiDocument, type EditorDocument } from "@/editor/core/document.ts";

const SIZE = 512;
const DEBOUNCE_MS = 150;

interface LoupeProps {
  doc: EditorDocument;
  /** Pointer position in document (TV) pixels, or `null` when the pointer left the canvas. */
  point: { x: number; y: number } | null;
}

export function Loupe({ doc, point }: LoupeProps) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const previous = useRef<string | null>(null);
  const x = point ? clamp(Math.round(point.x - SIZE / 2), doc.canvas.width - SIZE) : 0;
  const y = point ? clamp(Math.round(point.y - SIZE / 2), doc.canvas.height - SIZE) : 0;
  const active = point !== null;

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      renderRegion(toApiDocument(doc), { x, y, w: SIZE, h: SIZE }, controller.signal)
        .then((blob) => {
          if (previous.current) URL.revokeObjectURL(previous.current);
          previous.current = URL.createObjectURL(blob);
          setUrl(previous.current);
          setError(false);
        })
        .catch((reason: unknown) => {
          if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [active, doc, x, y]);

  useEffect(
    () => () => {
      if (previous.current) URL.revokeObjectURL(previous.current);
    },
    [],
  );

  const side = SIZE / (window.devicePixelRatio || 1);
  return (
    <div
      className="pointer-events-none absolute top-3 right-3 z-10 overflow-hidden rounded-md border border-border bg-panel shadow-2xl"
      style={{ width: side, height: side }}
    >
      {url && !error ? (
        <img
          src={url}
          alt={t("editor.loupe.title")}
          width={side}
          height={side}
          style={{ imageRendering: "pixelated", width: side, height: side }}
        />
      ) : (
        <div className="flex h-full items-center justify-center p-3 text-center text-[11px] text-muted">
          {error ? t("editor.loupe.error") : t("editor.loupe.hint")}
        </div>
      )}
      <span className="absolute right-1 bottom-1 rounded bg-black/60 px-1 text-[10px] text-white/80 tabular-nums">
        100% · {x},{y}
      </span>
    </div>
  );
}

const clamp = (value: number, max: number) => Math.min(Math.max(0, value), Math.max(0, max));
