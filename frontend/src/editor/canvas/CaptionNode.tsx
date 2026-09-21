// Captions on the canvas.
//
// The node's origin is the caption's *anchor point* (`x`, `y` = the baseline anchor) and the text
// is shifted off it with `offsetX`/`offsetY`, so Konva rotates the caption around that point —
// which is what the renderer does (`_draw_caption` pivots on the anchor, §8.1 step 4).
import { useEffect, useMemo, useState } from "react";
import { Text } from "react-konva";

import type { DocCaption } from "@/editor/core/document.ts";
import { anchorShift, baselineOffset, fontFamily, loadFont, measureText } from "./fonts.ts";

export function CaptionNode({ caption, hidden = false }: { caption: DocCaption; hidden?: boolean }) {
  const [ready, setReady] = useState(false);
  const family = fontFamily(caption.font, caption.weight);

  useEffect(() => {
    let active = true;
    void loadFont(caption.font, caption.weight).then(() => active && setReady(true));
    return () => {
      active = false;
    };
  }, [caption.font, caption.weight]);

  const spacing = caption.letter_spacing * caption.size;
  // Measured with whatever the canvas will actually draw with: the fallback until the bundled
  // face has loaded, the real font afterwards (their metrics differ).
  const drawn = ready ? family : FALLBACK;
  const width = useMemo(
    () => measureText(caption.text, caption.size, drawn, caption.weight, spacing),
    [caption.text, caption.size, drawn, caption.weight, spacing],
  );
  const baseline = useMemo(
    () => baselineOffset(caption.size, drawn, caption.weight),
    [caption.size, drawn, caption.weight],
  );

  return (
    <Text
      text={caption.text}
      x={caption.x}
      y={caption.y}
      offsetX={-anchorShift(width, caption.anchor, spacing)}
      offsetY={baseline}
      rotation={caption.rotation}
      fontFamily={family}
      fontSize={caption.size}
      fontStyle={String(caption.weight)}
      fill={caption.color}
      letterSpacing={spacing}
      visible={!hidden}
      listening={false}
    />
  );
}

const FALLBACK = "sans-serif";

