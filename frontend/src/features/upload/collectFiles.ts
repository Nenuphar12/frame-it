/** Collect files from a drop event, recursing into dropped folders. */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items)
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => Boolean(entry));
  if (entries.length === 0) return Array.from(dt.files);
  const nested = await Promise.all(entries.map(readEntry));
  return nested.flat();
}

async function readEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    return new Promise((resolve) =>
      (entry as FileSystemFileEntry).file(
        (file) => resolve([file]),
        () => resolve([]),
      ),
    );
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const children: FileSystemEntry[] = [];
    // readEntries returns results in batches until an empty batch.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve) =>
        reader.readEntries(resolve, () => resolve([])),
      );
      if (batch.length === 0) break;
      children.push(...batch);
    }
    const nested = await Promise.all(children.map(readEntry));
    return nested.flat();
  }
  return [];
}

export function hasFiles(event: DragEvent | React.DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}
