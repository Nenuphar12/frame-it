// `.tfstyle.json` / `.tflayout.json` files (docs/templates.md §6).
//
// Export is a plain download built in the browser from the template the list already holds;
// import reads the file and posts it, so the server validates the document exactly as it would
// validate a hand-written one. No secure-context API is involved (invariant 8).
import type { TemplateKind } from "@/api/queries";

export const FILE_VERSION = 1;
const EXTENSION: Record<TemplateKind, string> = {
  frame_style: "tfstyle",
  layout: "tflayout",
};

export interface TemplateFileContents {
  kind: string;
  version: number;
  name: string;
  document: Record<string, unknown>;
}

function slug(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "") || "template"
  );
}

/** Download `template` as a JSON file named after it. */
export function downloadTemplate(kind: TemplateKind, name: string, document: unknown): void {
  const contents: TemplateFileContents = {
    kind: EXTENSION[kind],
    version: FILE_VERSION,
    name,
    document: document as Record<string, unknown>,
  };
  const blob = new Blob([JSON.stringify(contents, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document_link(url, `${slug(name)}.${EXTENSION[kind]}.json`);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function document_link(url: string, filename: string): HTMLAnchorElement {
  const link = window.document.createElement("a");
  link.href = url;
  link.download = filename;
  window.document.body.append(link);
  return link;
}

/** Read a picked file; the shape is checked by the server, this only parses it. */
export async function readTemplateFile(file: File): Promise<Record<string, unknown>> {
  const parsed: unknown = JSON.parse(await file.text());
  if (typeof parsed !== "object" || parsed === null) throw new Error("invalid_template");
  return parsed as Record<string, unknown>;
}

export const fileAccept = (kind: TemplateKind): string => `.json,.${EXTENSION[kind]}`;
