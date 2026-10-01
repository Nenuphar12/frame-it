import { cn } from "@/shared/cn";

/**
 * A tag's colour, as a dot beside its name. A user colour never carries the text: the name keeps
 * the theme's tokens, so a pale yellow tag stays readable in both themes (invariant 16).
 */
export function TagDot({ color, className }: { color: string | null; className?: string }) {
  if (!color) return null;
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ backgroundColor: color }}
    />
  );
}
