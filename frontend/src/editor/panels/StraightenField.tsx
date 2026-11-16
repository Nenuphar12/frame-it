import { useTranslation } from "react-i18next";

import * as actions from "@/editor/actions";
import type { DocSlot } from "@/editor/core/document.ts";
import {
  flashStraightenGuides,
  holdStraightenGuides,
  releaseStraightenGuides,
} from "@/editor/guides";

import { Field, NumberField, Slider } from "./Controls";

/** The slider's travel: a horizon is rarely more than a few degrees off. The field goes to ±45. */
const SLIDER_DEGREES = 15;

/**
 * Straighten the photo — a tilted horizon, say (user feedback). The photo turns around its centre
 * and zooms in just enough to hide the corners (`geometry.straightenedSize`); one control for
 * the Simple panel and the Advanced framing panel.
 */
export function StraightenField({ slot }: { slot: DocSlot }) {
  const { t } = useTranslation();
  const value = slot.source.straighten;
  const typed = (degrees: number) => {
    actions.endStraighten(); // a typed value is a gesture of its own
    actions.setStraighten(degrees);
    flashStraightenGuides();
  };
  // While the photo turns, a grid over it gives the eye something straight to line up against.
  const slid = (degrees: number) => {
    actions.setStraighten(degrees);
    flashStraightenGuides(); // held by the pointer, or a moment for the arrow keys
  };
  return (
    <>
      <Field label={t("editor.straighten")}>
        <Slider
          value={value}
          min={-SLIDER_DEGREES}
          max={SLIDER_DEGREES}
          step={0.1}
          onChange={slid}
          onStart={holdStraightenGuides}
          onCommit={() => {
            actions.endStraighten();
            releaseStraightenGuides();
          }}
        />
        <NumberField value={value} min={-45} max={45} step={0.1} suffix="°" onChange={typed} />
      </Field>
      {value !== 0 && (
        <button
          type="button"
          onClick={() => typed(0)}
          className="self-start rounded border border-border px-1.5 py-0.5 text-[11px] text-muted hover:text-text"
        >
          {t("editor.straightenReset")}
        </button>
      )}
    </>
  );
}
