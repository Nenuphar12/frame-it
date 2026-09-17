import { UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { filesFromDataTransfer, hasFiles } from "./collectFiles";
import { useUploads } from "./uploadStore";

/** Window-wide drop target for files and folders (desktop). */
export function GlobalDropZone() {
  const { t } = useTranslation();
  const add = useUploads((s) => s.add);
  const [visible, setVisible] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current += 1;
      setVisible(true);
    };
    const onLeave = () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setVisible(false);
    };
    const onOver = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };
    const onDrop = async (event: DragEvent) => {
      if (!event.dataTransfer || !hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setVisible(false);
      add(await filesFromDataTransfer(event.dataTransfer));
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [add]);

  if (!visible) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-8">
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-accent bg-panel/80">
        <UploadCloud size={48} className="text-accent" />
        <p className="text-lg font-medium">{t("upload.dropTitle")}</p>
        <p className="text-sm text-muted">{t("upload.dropHint")}</p>
      </div>
    </div>
  );
}
