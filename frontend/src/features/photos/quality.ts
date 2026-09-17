import type { Photo } from "@/api/client";

export const TV_WIDTH = 3840;
export const TV_HEIGHT = 2160;

/** Whether the photo can fill the TV at native resolution or better (no upscaling). */
export function coversTv(photo: Pick<Photo, "width" | "height">): boolean {
  return photo.width >= TV_WIDTH && photo.height >= TV_HEIGHT;
}
