// Photo proxies for the canvas, drawn once into the slot's oriented space.
//
// A slot's crop is expressed in the photo's *oriented* source (EXIF orientation, then the slot's
// own `orient`, §7.1). Baking the rotation/flip into an offscreen canvas once means the canvas
// code can use plain `crop` rectangles, and Konva never has to re-read a flipped image.
import { useEffect, useState } from "react";

import { photoProxyUrl } from "@/api/client";
import type { Orient } from "@/editor/core/geometry.ts";

export interface OrientedProxy {
  image: CanvasImageSource;
  /** Size of `image` (the proxy in oriented space) — the crop is scaled by source → proxy. */
  width: number;
  height: number;
}

const proxies = new Map<string, Promise<HTMLImageElement>>();
const oriented = new Map<string, OrientedProxy>();

function loadProxy(photoId: string): Promise<HTMLImageElement> {
  const existing = proxies.get(photoId);
  if (existing) return existing;
  const promise = new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`proxy ${photoId}`));
    image.src = photoProxyUrl(photoId);
  });
  // Forget a failed load, or one hiccup (a restarted server, a dropped Wi-Fi packet) would leave
  // the slot empty for the whole session: the cache would keep handing back a rejected promise.
  proxies.set(
    photoId,
    promise.catch((reason: unknown) => {
      proxies.delete(photoId);
      throw reason;
    }),
  );
  return promise;
}

function orientKey(photoId: string, orient: Orient): string {
  return `${photoId}|${orient.rotate}|${orient.flip_h ? "f" : ""}`;
}

async function buildOriented(photoId: string, orient: Orient): Promise<OrientedProxy> {
  const key = orientKey(photoId, orient);
  const cached = oriented.get(key);
  if (cached) return cached;
  const proxy = await loadProxy(photoId);
  const turned = orient.rotate === 90 || orient.rotate === 270;
  const width = turned ? proxy.naturalHeight : proxy.naturalWidth;
  const height = turned ? proxy.naturalWidth : proxy.naturalHeight;
  let result: OrientedProxy = { image: proxy, width, height };
  if (orient.rotate !== 0 || orient.flip_h) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (context) {
      context.translate(width / 2, height / 2);
      context.rotate((orient.rotate * Math.PI) / 180);
      if (orient.flip_h) context.scale(-1, 1);
      context.drawImage(proxy, -proxy.naturalWidth / 2, -proxy.naturalHeight / 2);
      result = { image: canvas, width, height };
    }
  }
  oriented.set(key, result);
  return result;
}

/**
 * The slot's photo in oriented space, or `null` while it loads. The result is memoised in the
 * module, so the hook derives it from the cache and only re-renders when a new one is ready.
 */
export function useOrientedImage(photoId: string | null, orient: Orient): OrientedProxy | null {
  const key = photoId ? orientKey(photoId, orient) : null;
  const [, redraw] = useState(0);
  const proxy = key ? (oriented.get(key) ?? null) : null;

  useEffect(() => {
    if (!photoId || proxy) return;
    let active = true;
    buildOriented(photoId, orient)
      .then(() => active && redraw((value) => value + 1))
      .catch(() => undefined);
    return () => {
      active = false;
    };
    // `orient` is a fresh object on every render: the key carries its values.
  }, [key, photoId, orient, proxy]);

  return proxy;
}
