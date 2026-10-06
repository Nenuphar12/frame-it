"""The bundled recipe catalogue (docs/simple-editor.md §3.1, §6.4).

Recipes are **not** templates: they have stable ids, live in `assets/presets/recipes.json` and are
never user-editable, so there is no DB table and nothing to seed. `GET /api/v1/recipes` serves this
same file, which is how the client solves and draws its picker schemas from one source.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from frame_it.domain.composition import Recipe, RecipeCatalog
from frame_it.domain.document import RecipeSpec

RECIPES_FILE = Path(__file__).resolve().parent.parent / "assets" / "presets" / "recipes.json"


@lru_cache(maxsize=1)
def catalog() -> RecipeCatalog:
    """Parsed catalogue (validated once, then cached — the file ships with the package)."""
    return RecipeCatalog.model_validate(json.loads(RECIPES_FILE.read_text()))


def all_recipes() -> list[Recipe]:
    return list(catalog().recipes)


def find(recipe_id: str) -> Recipe | None:
    return next((r for r in catalog().recipes if r.id == recipe_id), None)


def spec(recipe_id: str) -> RecipeSpec | None:
    """`validate_references`' view of a recipe: slot count and balance range."""
    recipe = find(recipe_id)
    return recipe.spec() if recipe else None


def for_count(count: int) -> Recipe | None:
    """First catalogue entry holding `count` cells — the fallback of §4.4."""
    return next((r for r in catalog().recipes if r.count == count), None)
