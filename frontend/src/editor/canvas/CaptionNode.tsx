// Captions on the canvas. Read-only in Phase 5 (adding and editing them is Phase 6, §14): they
// are drawn so an imported or template-provided caption is visible while framing the photo.
import { useEffect, useMemo, useState } from "react";
import { Text } from "react-konva";

import type { DocCaption } from "@/editor/core/document.ts";
import { anchorShift, baselineOffset, fontFamily, loadFont, measureText } from "./fonts.ts";

export function CaptionNode({ caption }: { caption: DocCaption }) {
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
      x={caption.x + anchorShift(width, caption.anchor, spacing)}
      y={caption.y - baseline}
      rotation={caption.rotation}
      fontFamily={family}
      fontSize={caption.size}
      fontStyle={String(caption.weight)}
      fill={caption.color}
      letterSpacing={spacing}
      listening={false}
    />
  );
}

const FALLBACK = "sans-serif";

