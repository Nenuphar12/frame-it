import { useMemo } from "react";

import type { ArtworkSummary } from "@/api/client";
import { useArtworkActions, useTrashActions } from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";

interface GridCommandsInput {
  /** The rows currently shown, in order — the selection is read against them. */
  items: ArtworkSummary[];
  selected: Set<string>;
  selectAll: () => void;
  clear: () => void;
  openEditor: (id: string) => void;
  /** Opens the add-to-collection menu anchored on the page's own button. */
  openCollectionMenu: () => void;
  /** Focus the page's search box, when it has one (a callback, not the ref: reading a ref inside
   * the memo is what the React Compiler lint forbids). */
  focusSearch?: () => void;
  /** Remove the selection from the collection being shown (only a manual one has this). */
  removeFromCollection?: (artworkIds: string[]) => void;
  /**
   * A modal is open. It registers `f`, `e`, `c` and `Delete` of its own, so the grid keeps its
   * palette entries but gives up the keys — one press must not act twice.
   */
  suspended?: boolean;
}

/**
 * The keyboard for any grid of artworks: Artworks, Favorites, a collection's page. One hook so the
 * three cannot drift — the collection page adds `Backspace` on top rather than growing its own set.
 */
export function useArtworkGridCommands({
  items,
  selected,
  selectAll,
  clear,
  openEditor,
  openCollectionMenu,
  focusSearch,
  removeFromCollection,
  suspended = false,
}: GridCommandsInput) {
  const { update } = useArtworkActions();
  const { artworks: trashArtworks } = useTrashActions();
  const ids = useMemo(() => items.map((a) => a.id), [items]);
  const inOrder = useMemo(() => ids.filter((id) => selected.has(id)), [ids, selected]);

  const commands = useMemo<Command[]>(() => {
    const key = (shortcut: string) => (suspended ? undefined : shortcut);
    const group = "commands.groups.library";
    const list: Command[] = [
      {
        id: "artworks.selectAll",
        label: "artworks.selectAll",
        group,
        shortcut: key("$mod+a"),
        run: selectAll,
      },
      {
        id: "artworks.clear",
        label: "photos.clearSelection",
        group,
        shortcut: key("Escape"),
        run: clear,
      },
      {
        id: "artworks.addToCollection",
        label: "collections.addTo",
        group,
        shortcut: key("c"),
        run: () => {
          if (inOrder.length > 0) openCollectionMenu();
        },
      },
      {
        id: "artworks.favorite",
        label: "artworks.toggleFavorite",
        group,
        shortcut: key("f"),
        run: () => {
          // One gesture for the whole selection: if any is not a favourite, they all become one.
          const chosen = items.filter((a) => selected.has(a.id));
          const turnOn = chosen.some((a) => !a.favorite);
          for (const artwork of chosen) {
            if (artwork.favorite !== turnOn) update.mutate({ id: artwork.id, favorite: turnOn });
          }
        },
      },
      {
        id: "artworks.edit",
        label: "editor.open",
        group,
        shortcut: key("e"),
        run: () => {
          const first = inOrder[0];
          if (first) openEditor(first);
        },
      },
      {
        id: "artworks.trash",
        label: "trash.moveToTrash",
        group,
        shortcut: key("Delete"),
        run: () => {
          if (inOrder.length > 0) {
            trashArtworks.mutate(inOrder);
            clear();
          }
        },
      },
    ];
    if (focusSearch) {
      list.push({
        id: "artworks.search",
        label: "artworks.focusSearch",
        group,
        shortcut: key("/"),
        run: focusSearch,
      });
    }
    if (removeFromCollection) {
      // `Delete` trashes everywhere; taking an artwork *out of a collection* is a different, far
      // gentler act and deserves its own key (remarks.md #6).
      list.push({
        id: "collections.removeItems",
        label: "collections.removeFromCollection",
        group,
        shortcut: key("Backspace"),
        run: () => {
          if (inOrder.length > 0) {
            removeFromCollection(inOrder);
            clear();
          }
        },
      });
    }
    return list;
  }, [
    clear,
    focusSearch,
    inOrder,
    items,
    openCollectionMenu,
    openEditor,
    removeFromCollection,
    selectAll,
    selected,
    suspended,
    trashArtworks,
    update,
  ]);
  useRegisterCommands(commands);

  return { selectedInOrder: inOrder };
}
