import { useCallback, useState, type MouseEvent } from "react";

interface SelectionOptions {
  /**
   * A picker (tick what you want, then confirm): a plain click toggles one item instead of
   * replacing the selection. Shift-click still adds a range, Ctrl/Cmd-click still toggles.
   */
  toggle?: boolean;
  /** Shown but not selectable (already in the collection): ranges and select-all skip them. */
  disabled?: ReadonlySet<string>;
}

/**
 * Grid selection with click, Ctrl/Cmd-click toggle and Shift-click ranges.
 *
 * The range anchor is an **id**, not an index: a list can change between two clicks — a photo
 * lands in the Inbox or leaves it — and an index would then point at another item, so the range
 * started somewhere else or nowhere (user feedback: Shift-click "works in Photos, not in the
 * Inbox", the one grid that moves under the pointer).
 */
export function useSelection(orderedIds: string[], options: SelectionOptions = {}) {
  const { toggle = false, disabled } = options;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<string | null>(null);

  const click = useCallback(
    (id: string, index: number, event: MouseEvent) => {
      const flip = toggle || event.metaKey || event.ctrlKey;
      const from = anchor === null ? -1 : orderedIds.indexOf(anchor);
      const at = orderedIds[index] === id ? index : orderedIds.indexOf(id);
      setSelected((current) => {
        const next = new Set(flip || event.shiftKey ? current : []);
        if (event.shiftKey && from >= 0 && at >= 0) {
          const [start, end] = from < at ? [from, at] : [at, from];
          for (const value of orderedIds.slice(start, end + 1)) {
            if (!disabled?.has(value)) next.add(value);
          }
        } else if (flip) {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        } else {
          next.add(id);
        }
        return next;
      });
      if (!event.shiftKey || from < 0) setAnchor(id);
    },
    [anchor, disabled, orderedIds, toggle],
  );

  /** One item in or out, whatever the click mode (the photo viewer's `s`). */
  const toggleOne = useCallback(
    (id: string) => {
      if (disabled?.has(id)) return;
      setSelected((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      setAnchor(id);
    },
    [disabled],
  );

  const selectAll = useCallback(
    () => setSelected(new Set(orderedIds.filter((id) => !disabled?.has(id)))),
    [disabled, orderedIds],
  );
  const clear = useCallback(() => setSelected(new Set()), []);
  const prune = useCallback(
    (validIds: Set<string>) =>
      setSelected((current) => new Set([...current].filter((id) => validIds.has(id)))),
    [],
  );

  // `anchor`: the item last clicked or toggled — what a keyboard "open this one" means.
  return { selected, anchor, click, toggleOne, selectAll, clear, prune };
}
