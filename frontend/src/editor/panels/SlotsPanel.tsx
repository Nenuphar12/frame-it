// The slots of a composition: z-order (the list *is* the z-order), photos, add/remove.
//
// The list is shown front-most first — that is how the canvas reads — while the document stores
// the back-most slot first (`docs/artwork-document.md`), so the indices are mirrored here.
import {
  ArrowDown,
  ArrowUp,
  Image as ImageIcon,
  ImageOff,
  Maximize,
  Minimize,
  Plus,
  Repeat,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { photoThumbUrl } from "@/api/client";
import * as actions from "@/editor/actions";
import type { EditorDocument } from "@/editor/core/document.ts";
import { MAX_SLOTS } from "@/editor/operations";
import { cn } from "@/shared/cn";
import { SLOT_MIME, startInternalDrag } from "@/shared/dnd";
import { IconButton, PanelSection } from "./Controls";
import { PhotoPicker } from "./PhotoPicker";
import { SlotQualityBadge } from "./QualityBadge";

interface SlotsPanelProps {
  doc: EditorDocument;
  selectedIds: string[];
  onSelect: (slotId: string, additive: boolean) => void;
}

export function SlotsPanel({ doc, selectedIds, onSelect }: SlotsPanelProps) {
  const { t } = useTranslation();
  /** `add` picks a photo for a new slot, an id picks a replacement for that slot. */
  const [picking, setPicking] = useState<"add" | string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const front = [...doc.slots].reverse();
  const used = doc.slots.flatMap((slot) => (slot.photo_id ? [slot.photo_id] : []));
  const selectedCount = selectedIds.length;

  /** Document index of a slot shown at `position` in the front-first list. */
  const toDocumentIndex = (position: number) => doc.slots.length - 1 - position;

  return (
    <PanelSection
      title={t("editor.sections.slots")}
      action={
        <div className="flex items-center gap-1">
          <IconButton
            title={t("editor.slots.add")}
            disabled={doc.slots.length >= MAX_SLOTS}
            onClick={() => setPicking("add")}
          >
            <Plus size={14} />
          </IconButton>
          <IconButton
            title={t("editor.slots.remove")}
            disabled={selectedCount === 0}
            onClick={actions.removeSelectedSlots}
          >
            <Trash2 size={14} />
          </IconButton>
        </div>
      }
    >
      <ul className="flex flex-col gap-1">
        {front.map((slot, position) => (
          <li
            key={slot.id}
            draggable
            onDragStart={(event) => {
              startInternalDrag(event.dataTransfer, SLOT_MIME, slot.id);
              setDragging(slot.id);
            }}
            onDragEnd={() => setDragging(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              if (!dragging || dragging === slot.id) return;
              const from = doc.slots.findIndex((item) => item.id === dragging);
              actions.reorderSlots(from, toDocumentIndex(position));
              setDragging(null);
            }}
            className={cn(
              "flex items-center gap-2 rounded border border-border p-1 text-xs",
              selectedIds.includes(slot.id) && "border-accent bg-panel-2",
              dragging === slot.id && "opacity-50",
            )}
          >
            <button
              type="button"
              onClick={(event) =>
                onSelect(slot.id, event.shiftKey || event.ctrlKey || event.metaKey)
              }
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              <span className="h-8 w-12 shrink-0 overflow-hidden rounded bg-panel-2">
                {slot.photo_id ? (
                  <img
                    src={photoThumbUrl(slot.photo_id, 256)}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <ImageOff size={14} className="m-auto mt-2 text-muted" />
                )}
              </span>
              <span className="min-w-0 flex-1 truncate">
                {slot.photo_id
                  ? t("editor.slots.slot", { index: front.length - position })
                  : t("editor.quality.empty")}
              </span>
              <SlotQualityBadge slot={slot} />
            </button>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-1">
        <IconButton
          title={t("editor.slots.replacePhoto")}
          disabled={selectedCount !== 1}
          onClick={() => selectedIds[0] && setPicking(selectedIds[0])}
        >
          <ImageIcon size={14} />
        </IconButton>
        <IconButton
          title={t("editor.slots.clearPhoto")}
          disabled={
            selectedCount !== 1 ||
            !selectedIds[0] ||
            !doc.slots.find((slot) => slot.id === selectedIds[0])?.photo_id
          }
          onClick={() => selectedIds[0] && void actions.setSlotPhoto(selectedIds[0], null)}
        >
          <ImageOff size={14} />
        </IconButton>
        <IconButton
          title={t("editor.slots.swap")}
          disabled={selectedCount !== 2}
          onClick={() =>
            selectedIds[0] && selectedIds[1] && actions.swapPhotos(selectedIds[0], selectedIds[1])
          }
        >
          <Repeat size={14} />
        </IconButton>
        <IconButton
          title={t("editor.slots.fitToPhoto")}
          disabled={selectedCount === 0}
          onClick={actions.fitSlotToPhoto}
        >
          <Minimize size={14} />
        </IconButton>
        <IconButton
          title={t("editor.slots.fillSlot")}
          disabled={selectedCount === 0}
          onClick={actions.fillSlotWithPhoto}
        >
          <Maximize size={14} />
        </IconButton>
        <span className="mx-1 h-4 w-px bg-border" />
        <IconButton
          title={t("editor.slots.bringForward")}
          disabled={selectedCount !== 1}
          onClick={() => actions.moveInOrder(1)}
        >
          <ArrowUp size={14} />
        </IconButton>
        <IconButton
          title={t("editor.slots.sendBackward")}
          disabled={selectedCount !== 1}
          onClick={() => actions.moveInOrder(-1)}
        >
          <ArrowDown size={14} />
        </IconButton>
      </div>

      <PhotoPicker
        open={picking !== null}
        onOpenChange={(open) => !open && setPicking(null)}
        used={used}
        onPickEmpty={picking === "add" ? () => void actions.addSlot(null) : undefined}
        onPick={(photoId) => {
          if (picking === "add") void actions.addSlot(photoId);
          else if (picking) void actions.setSlotPhoto(picking, photoId);
          setPicking(null);
        }}
      />
    </PanelSection>
  );
}
