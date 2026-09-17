import { useCallback, useState, type MouseEvent } from "react";

/** Grid selection with click, Ctrl/Cmd-click toggle and Shift-click ranges. */
export function useSelection(orderedIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);

  const click = useCallback(
    (id: string, index: number, event: MouseEvent) => {
      setSelected((current) => {
        const next = new Set(event.metaKey || event.ctrlKey || event.shiftKey ? current : []);
        if (event.shiftKey && anchor !== null) {
          const [from, to] = anchor < index ? [anchor, index] : [index, anchor];
          orderedIds.slice(from, to + 1).forEach((value) => next.add(value));
        } else if (event.metaKey || event.ctrlKey) {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        } else {
          next.add(id);
        }
        return next;
      });
      if (!event.shiftKey) setAnchor(index);
    },
    [anchor, orderedIds],
  );

  const selectAll = useCallback(() => setSelected(new Set(orderedIds)), [orderedIds]);
  const clear = useCallback(() => setSelected(new Set()), []);
  const prune = useCallback(
    (validIds: Set<string>) =>
      setSelected((current) => new Set([...current].filter((id) => validIds.has(id)))),
    [],
  );

  return { selected, click, selectAll, clear, prune };
}
