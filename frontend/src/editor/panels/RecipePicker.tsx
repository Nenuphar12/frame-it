// The layout picker of the Simple panel (docs/simple-editor.md §6.3).
//
// Every schema is drawn by the solver itself — one `solve` at thumbnail parameters, rendered as
// SVG rects with the cell number. No hand-drawn assets: a new recipe in `recipes.json` shows up
// here with a correct schema for free, and the thumbnail cannot drift from the real layout.
import { useTranslation } from "react-i18next";

import { CANVAS } from "@/editor/core/geometry.ts";
import { solve, type Composition, type Recipe } from "@/editor/core/composition.ts";
import { cn } from "@/shared/cn";

/** Thumbnail parameters: `outer` 6 % of the canvas, `gutter` 4 %, always `fill` (§6.3). */
const SCHEMA: Composition = {
  recipe: "",
  balance: null,
  outer: { x: Math.round(CANVAS.w * 0.06), y: Math.round(CANVAS.h * 0.06) },
  gutter: { x: Math.round(CANVAS.w * 0.04), y: Math.round(CANVAS.h * 0.04) },
  format: "fill",
  border: null,
  caption: { text: "", place: "none" },
  detached: false,
};

export function RecipeSchema({ recipe, numbered = true }: { recipe: Recipe; numbered?: boolean }) {
  const cells = solve(recipe, { ...SCHEMA, recipe: recipe.id });
  return (
    <svg
      viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`}
      className="h-full w-full"
      role="presentation"
      focusable="false"
    >
      {cells.map((cell, index) => (
        <g key={cell.id}>
          <rect
            x={cell.rect.x}
            y={cell.rect.y}
            width={cell.rect.w}
            height={cell.rect.h}
            rx={40}
            fill="currentColor"
            opacity={0.32}
          />
          {numbered && (
            <text
              x={cell.rect.x + cell.rect.w / 2}
              y={cell.rect.y + cell.rect.h / 2}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={Math.min(cell.rect.w, cell.rect.h) * 0.55}
              fill="currentColor"
            >
              {index + 1}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

export function RecipePicker({
  recipes,
  selected,
  onSelect,
}: {
  recipes: Recipe[];
  selected: string | null;
  onSelect: (recipeId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="grid grid-cols-4 gap-1.5"
      role="radiogroup"
      aria-label={t("editor.simple.layout")}
    >
      {recipes.map((recipe) => {
        const name = t(recipe.name_key, { defaultValue: recipe.id });
        return (
          <button
            key={recipe.id}
            type="button"
            role="radio"
            aria-checked={recipe.id === selected}
            title={name}
            aria-label={name}
            onClick={() => onSelect(recipe.id)}
            className={cn(
              "aspect-video rounded border p-0.5 text-muted",
              recipe.id === selected
                ? "border-accent text-accent"
                : "border-border hover:text-text",
            )}
          >
            <RecipeSchema recipe={recipe} />
          </button>
        );
      })}
    </div>
  );
}
