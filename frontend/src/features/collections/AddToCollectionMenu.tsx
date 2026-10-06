import * as Popover from "@radix-ui/react-popover";
import { Check, FolderPlus, Plus } from "lucide-react";
import { forwardRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useCollectionItems, useCollections, useCreateCollection } from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";

interface AddToCollectionMenuProps {
  artworkIds: string[];
  /** Collections the artwork already belongs to: they get a tick and remove instead of add. */
  memberOf?: string[];
  onDone?: () => void;
  trigger?: ReactNode;
  /** Opened by a keyboard shortcut rather than by the trigger (the button stays the anchor). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * Files artworks into a manual collection — from the Artworks grid, from the viewer, or from a
 * keyboard shortcut. It can **create** the collection on the spot (user feedback): the common case
 * is realizing halfway through a selection that the collection you want does not exist yet.
 */
export const AddToCollectionMenu = forwardRef<HTMLButtonElement, AddToCollectionMenuProps>(
  function AddToCollectionMenu(
    { artworkIds, memberOf = [], onDone, trigger, open, onOpenChange },
    ref,
  ) {
    const { t } = useTranslation();
    const collections = useCollections();
    const items = useCollectionItems();
    const create = useCreateCollection();
    const [name, setName] = useState("");
    const manual = (collections.data ?? []).filter((c) => c.kind === "manual");
    const member = new Set(memberOf);

    const toggle = (collectionId: string) => {
      if (member.has(collectionId)) {
        items.remove.mutate({ id: collectionId, artwork_ids: artworkIds });
      } else {
        items.add.mutate({ id: collectionId, artwork_ids: artworkIds });
      }
      onDone?.();
    };

    const createAndAdd = async () => {
      const trimmed = name.trim();
      if (!trimmed) return;
      const collection = await create.mutateAsync({ name: trimmed });
      setName("");
      items.add.mutate({ id: collection.id, artwork_ids: artworkIds });
      onDone?.();
      onOpenChange?.(false);
    };

    return (
      <Popover.Root open={open} onOpenChange={onOpenChange}>
        <Popover.Trigger asChild ref={ref}>
          {trigger ?? (
            <Button size="sm" variant="ghost" disabled={artworkIds.length === 0}>
              <FolderPlus size={14} /> {t("collections.addTo")}
            </Button>
          )}
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            onEscapeKeyDown={(event) => event.stopPropagation()}
            sideOffset={6}
            className="z-50 w-64 rounded-md border border-border bg-panel p-1 shadow-xl"
          >
            <div className="max-h-56 overflow-y-auto">
              {manual.length === 0 && (
                <p className="p-2 text-xs text-muted">{t("collections.emptyTree")}</p>
              )}
              {manual.map((collection) => (
                <button
                  key={collection.id}
                  type="button"
                  onClick={() => toggle(collection.id)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-panel-2"
                >
                  <Check
                    size={13}
                    className={cn(
                      "shrink-0 text-accent",
                      member.has(collection.id) ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{collection.name}</span>
                </button>
              ))}
            </div>
            <form
              className="mt-1 flex gap-1 border-t border-border pt-1"
              onSubmit={(event) => {
                event.preventDefault();
                void createAndAdd();
              }}
            >
              <input
                value={name}
                maxLength={256}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("collections.newPlaceholder")}
                className="min-w-0 flex-1 rounded bg-transparent px-1.5 py-1 text-sm outline-none placeholder:text-muted"
              />
              <Button type="submit" size="sm" variant="ghost" disabled={!name.trim()}>
                <Plus size={13} /> {t("collections.createAndAdd")}
              </Button>
            </form>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    );
  },
);
