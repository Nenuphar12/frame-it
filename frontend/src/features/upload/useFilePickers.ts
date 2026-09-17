import { useUploads } from "./uploadStore";

/** Hidden inputs for "Add photos" / "Add folder"; returns openers. */
export function useFilePickers() {
  const add = useUploads((s) => s.add);
  const open = (directory: boolean) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    if (directory) input.webkitdirectory = true;
    else input.accept = "image/jpeg,image/png,image/avif,.jpg,.jpeg,.png,.avif";
    input.onchange = () => add(Array.from(input.files ?? []));
    input.click();
  };
  return { openFiles: () => open(false), openFolder: () => open(true) };
}
