import { isFinished, useUploads, type UploadItem } from "./uploadStore";

export function useUploadSummary() {
  const items = useUploads((s) => s.items);
  const count = (pred: (i: UploadItem) => boolean) => items.filter(pred).length;
  return {
    total: items.length,
    done: count((i) => i.status === "done"),
    duplicate: count((i) => i.status === "duplicate" || i.status === "merged"),
    problems: count((i) => i.status === "failed" || i.status === "rejected"),
    active: count((i) => !isFinished(i.status)),
  };
}
