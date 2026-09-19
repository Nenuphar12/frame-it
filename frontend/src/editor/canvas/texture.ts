// Mat texture tile, tinted exactly like the renderer (docs/rendering-spec.md §8.1 step 2):
//   out = clamp(floor(mat + strength × (tile − 128) + 0.5), 0, 255)
// S3 measured this as pixel-identical to pyvips, so the preview's mat needs no tolerance at all.
import { API_BASE } from "@/api/client";

const tiles = new Map<string, Promise<HTMLImageElement>>();
const tinted = new Map<string, HTMLCanvasElement>();

export const textureUrl = (id: string) => `${API_BASE}/textures/${id}.png`;

function loadTile(id: string): Promise<HTMLImageElement> {
  const existing = tiles.get(id);
  if (existing) return existing;
  const promise = new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`texture ${id}`));
    image.src = textureUrl(id);
  });
  // A failed load is forgotten so the next draw retries (see `useOrientedImage`).
  tiles.set(
    id,
    promise.catch((reason: unknown) => {
      tiles.delete(id);
      throw reason;
    }),
  );
  return promise;
}

function parseHex(color: string): [number, number, number] {
  const value = Number.parseInt(color.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** Cache key of a tinted tile; `cachedTile` returns it synchronously once it has been built. */
export const tileKey = (id: string, color: string, strength: number) =>
  `${id}|${color}|${strength}`;

export const cachedTile = (key: string): HTMLCanvasElement | null => tinted.get(key) ?? null;

/** Tinted tile for (texture, mat colour, strength); cached because it is rebuilt on every draw. */
export async function tintedTile(
  id: string,
  color: string,
  strength: number,
): Promise<HTMLCanvasElement> {
  const key = tileKey(id, color, strength);
  const cached = tinted.get(key);
  if (cached) return cached;
  const tile = await loadTile(id);
  const canvas = document.createElement("canvas");
  canvas.width = tile.naturalWidth;
  canvas.height = tile.naturalHeight;
  const context = canvas.getContext("2d");
  if (!context) return canvas;
  context.drawImage(tile, 0, 0);
  const data = context.getImageData(0, 0, canvas.width, canvas.height);
  const mat = parseHex(color);
  for (let i = 0; i < data.data.length; i += 4) {
    const grey = data.data[i] ?? 128;
    for (let channel = 0; channel < 3; channel++) {
      const value = Math.floor((mat[channel] ?? 0) + strength * (grey - 128) + 0.5);
      data.data[i + channel] = Math.min(255, Math.max(0, value));
    }
    data.data[i + 3] = 255;
  }
  context.putImageData(data, 0, 0);
  tinted.set(key, canvas);
  return canvas;
}
