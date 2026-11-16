// The straightening guides: a grid over the photo while it is being turned (user feedback), so a
// horizon or a wall can be lined up against something straight. UI state only, outside the
// document and the undo history — a store of its own, outside React like the editor's.
import { create } from "zustand";

export const useStraightenGuides = create<{ visible: boolean }>(() => ({ visible: false }));

/** How long the grid stays after the last change, so the result can be judged against it. */
const LINGER_MS = 900;

let held = false;
let timer: ReturnType<typeof setTimeout> | null = null;

function hideLater(): void {
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    if (!held) useStraightenGuides.setState({ visible: false });
  }, LINGER_MS);
}

/** The slider is grabbed: show the grid until it is let go. */
export function holdStraightenGuides(): void {
  held = true;
  if (timer !== null) clearTimeout(timer);
  timer = null;
  useStraightenGuides.setState({ visible: true });
}

/** The slider is let go: keep the grid a moment, then hide it. */
export function releaseStraightenGuides(): void {
  held = false;
  hideLater();
}

/** A change without a held slider (a typed value, the arrow keys): show the grid for a moment. */
export function flashStraightenGuides(): void {
  useStraightenGuides.setState({ visible: true });
  if (!held) hideLater();
}
