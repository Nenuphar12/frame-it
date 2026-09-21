// Multi-selection operations: align, distribute, same size, and copying the decorations.
//
// Everything works on the selection; the *primary* slot (the last one picked) is the reference
// for "same size" and for the decorations, like every other multi-object editor.
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalSpaceAround,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalSpaceAround,
  Copy,
  Square,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import * as actions from "@/editor/actions";
import type { Edge } from "@/editor/core/arrange.ts";
import { IconButton, PanelSection } from "./Controls";

const ALIGNMENTS: { edge: Edge; icon: typeof AlignStartVertical }[] = [
  { edge: "left", icon: AlignStartVertical },
  { edge: "h_center", icon: AlignCenterVertical },
  { edge: "right", icon: AlignEndVertical },
  { edge: "top", icon: AlignStartHorizontal },
  { edge: "v_center", icon: AlignCenterHorizontal },
  { edge: "bottom", icon: AlignEndHorizontal },
];

export function ArrangePanel({ selectedCount }: { selectedCount: number }) {
  const { t } = useTranslation();
  const few = selectedCount < 2;
  return (
    <PanelSection title={t("editor.sections.arrange")}>
      <div className="flex flex-wrap items-center gap-1">
        {ALIGNMENTS.map(({ edge, icon: Icon }) => (
          <IconButton
            key={edge}
            title={t(`editor.arrange.align.${edge}`)}
            disabled={few}
            onClick={() => actions.alignSlots(edge)}
          >
            <Icon size={14} />
          </IconButton>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <IconButton
          title={t("editor.arrange.distributeX")}
          disabled={selectedCount < 3}
          onClick={() => actions.distributeSlots("x")}
        >
          <AlignHorizontalSpaceAround size={14} />
        </IconButton>
        <IconButton
          title={t("editor.arrange.distributeY")}
          disabled={selectedCount < 3}
          onClick={() => actions.distributeSlots("y")}
        >
          <AlignVerticalSpaceAround size={14} />
        </IconButton>
        <span className="mx-1 h-4 w-px bg-border" />
        <IconButton
          title={t("editor.arrange.sameSize")}
          disabled={few}
          onClick={actions.sameSizeSlots}
        >
          <Square size={14} />
        </IconButton>
        <IconButton
          title={t("editor.arrange.applyDecorations")}
          disabled={few}
          onClick={actions.applyDecorations}
        >
          <Copy size={14} />
        </IconButton>
      </div>
      <p className="text-[11px] text-muted">
        {few ? t("editor.arrange.hint") : t("editor.arrange.selected", { count: selectedCount })}
      </p>
    </PanelSection>
  );
}
