"""Pure recipe validation, calculations and cooking projections."""
import copy
import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from mealie.schema.recipe.recipe import RecipeDraft

NUTRIENTS = ("calories", "protein", "carbohydrates", "fat", "saturatedFat", "fiber", "sugar", "sodium")
SYSTEM_FIELDS = {"id", "userId", "householdId", "groupId", "slug", "createdAt", "updatedAt", "dateAdded", "dateUpdated", "comments"}


def fingerprint(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def number(value: Any, label: str, maximum: float = 1e8) -> float:
    if isinstance(value, bool):
        raise HTTPException(422, f"{label} must be a number")
    try:
        out = float(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, f"{label} must be a number") from error
    if not math.isfinite(out) or out < 0 or out > maximum:
        raise HTTPException(422, f"{label} is outside its allowed range")
    return out


def validate(document: dict) -> dict:
    try:
        size = len(json.dumps(document, allow_nan=False))
    except (ValueError, TypeError) as error:
        raise HTTPException(422, "Recipe fields must contain valid finite JSON values") from error
    if not isinstance(document, dict) or size > 500_000:
        raise HTTPException(422, "Recipe must be an object below 500 KB")
    document = copy.deepcopy(document)
    for key in SYSTEM_FIELDS:
        document.pop(key, None)
    # Reject unknown top-level fields rather than silently losing an AI's work.
    known = {field.alias or name for name, field in RecipeDraft.model_fields.items()}
    unknown = set(document) - known
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}. Use extras for custom fields.")
    if not isinstance(document.get("name"), str) or not 1 <= len(document["name"].strip()) <= 240:
        raise HTTPException(422, "Give the recipe a name, up to 240 characters")
    try:
        parsed = RecipeDraft.model_validate(document)
    except ValidationError as error:
        raise HTTPException(422, "Invalid recipe fields: " + "; ".join(str(e["loc"]) + " " + e["msg"] for e in error.errors()[:8])) from error
    result = parsed.model_dump(mode="json", by_alias=True, exclude=SYSTEM_FIELDS)
    for key in SYSTEM_FIELDS:
        result.pop(key, None)
    result["recipeServings"] = number(result.get("recipeServings", 0), "Servings", 100_000)
    if result["recipeServings"] <= 0:
        raise HTTPException(422, "Servings must be greater than zero")
    result["settings"] = {**(result.get("settings") or {}), "public": False, "locked": True}
    if result.get("orgURL") and not re.match(r"^https?://", result["orgURL"]):
        raise HTTPException(422, "Source URL must use http or https")
    ext = result.setdefault("extras", {}).setdefault("hearth", {})
    if not isinstance(ext, dict):
        raise HTTPException(422, "extras.hearth must be an object")
    for key in ("components", "ingredientNutrition", "stepDetails", "appliances"):
        if not isinstance(ext.get(key, []), list):
            raise HTTPException(422, f"extras.hearth.{key} must be a list")
    ingredients = result.get("recipeIngredient", [])
    for item in ingredients:
        if item.get("referencedRecipe"):
            raise HTTPException(422, "Use version-pinned components in extras.hearth instead of live recipe links")
        item["quantity"] = number(item.get("quantity") or 0, "Ingredient quantity")
        if item.get("referenceId") is None:
            item["referenceId"] = str(uuid4())
    steps = result.get("recipeInstructions", [])
    for step in steps:
        if not step.get("id"):
            step["id"] = str(uuid4())
    component_ids: set[str] = set()
    for component in ext.get("components", []):
        if not isinstance(component, dict) or not component.get("id") or component["id"] in component_ids:
            raise HTTPException(422, "Every component needs a unique id")
        component_ids.add(component["id"])
        if not isinstance(component.get("dependsOn", []), list) or any(not isinstance(key, str) for key in component.get("dependsOn", [])):
            raise HTTPException(422, "Component dependencies must be a list of component IDs")
        for key, length in (("ingredientIndexes", len(ingredients)), ("stepIndexes", len(steps))):
            if not isinstance(component.get(key, []), list) or any(type(i) is not int or i < 0 or i >= length for i in component.get(key, [])):
                raise HTTPException(422, "Component contains an invalid ingredient or step index")
    visited: set[str] = set()
    active: set[str] = set()
    by_id = {c["id"]: c for c in ext.get("components", [])}

    def visit(key: str) -> None:
        if key in active or key not in by_id:
            raise HTTPException(422, "Component dependencies must exist and cannot be circular")
        if key in visited:
            return
        active.add(key)
        for dep in by_id[key].get("dependsOn", []):
            visit(dep)
        active.remove(key)
        visited.add(key)

    for key in by_id:
        visit(key)
    seen: set[int] = set()
    for entry in ext.get("ingredientNutrition", []):
        if not isinstance(entry, dict) or type(entry.get("index")) is not int or entry["index"] not in range(len(ingredients)) or entry["index"] in seen:
            raise HTTPException(422, "Nutrition entries need unique valid ingredient indexes")
        seen.add(entry["index"])
        if entry.get("grams") is not None:
            entry["grams"] = number(entry["grams"], "Edible grams")
        if "per100g" in entry:
            if not isinstance(entry["per100g"], dict) or not entry.get("source"):
                raise HTTPException(422, "Nutrition needs per100g values and a source")
            entry["per100g"] = {key: number(val, key) for key, val in entry["per100g"].items() if key in NUTRIENTS}
    cover = ext.get("cover", "")
    if cover and not re.fullmatch(r"/kitchen/media/[a-f0-9]{64}\.webp", cover):
        raise HTTPException(422, "Cover must be an uploaded kitchen image")
    ext["nutrition"] = calculate_nutrition(result)
    return result


def calculate_nutrition(document: dict, indexes: list[int] | None = None, factor: float = 1) -> dict:
    ext = document.get("extras", {}).get("hearth", {})
    ingredients = document.get("recipeIngredient", [])
    mappings = {x["index"]: x for x in ext.get("ingredientNutrition", [])}
    selected = indexes if indexes is not None else list(range(len(ingredients)))
    totals = {key: Decimal(0) for key in NUTRIENTS}
    missing: list[int] = []
    missing_nutrients = {key: [] for key in NUTRIENTS}
    for index in selected:
        entry = mappings.get(index, {})
        grams = entry.get("grams")
        # Weight units may be converted without guessing food densities.
        if grams is None:
            ingredient = ingredients[index]
            unit = (ingredient.get("unit") or {}).get("name", "").lower()
            multipliers = {"g": 1, "gram": 1, "grams": 1, "kg": 1000, "kilogram": 1000, "mg": 0.001}
            if unit in multipliers:
                grams = number(ingredient.get("quantity", 0), "Quantity") * multipliers[unit]
        values = entry.get("per100g", {})
        if grams is None or "calories" not in values:
            missing.append(index)
        for key in NUTRIENTS:
            if grams is None or key not in values:
                missing_nutrients[key].append(index)
            else:
                totals[key] += Decimal(str(number(grams, "Grams"))) * Decimal(str(number(values[key], key))) / 100
    servings = number(document.get("recipeServings") or 1, "Servings") or 1
    total = {key: round(float(val) * factor, 2) if selected and not missing_nutrients[key] else None for key, val in totals.items()}
    weight = ext.get("cookedWeightGrams")
    per100g = {key: round(float(val) / weight * 100, 2) if not missing_nutrients[key] else None for key, val in totals.items()} if isinstance(weight, (int, float)) and weight > 0 else None
    return {"total": total, "perServing": {key: round(float(val) / servings, 2) if selected and not missing_nutrients[key] else None for key, val in totals.items()},
            "per100g": per100g,
            "missingIngredients": missing, "missingNutrients": missing_nutrients,
            "complete": bool(selected) and not missing, "calculator": "hearth-1", "basis": "ingredient estimates",
            "kJ": round(total["calories"] * 4.184, 2) if total["calories"] is not None else None}


def cooking_view(document: dict, factor: float = 1, components: list[str] | None = None) -> dict:
    factor = number(factor, "Batch multiplier", 1000)
    if factor <= 0:
        raise HTTPException(422, "Batch multiplier must be positive")
    out = copy.deepcopy(document)
    available = {c["id"]: c for c in document.get("extras", {}).get("hearth", {}).get("components", [])}
    chosen: set[str] = set()

    def include(key: str) -> None:
        if key not in available:
            raise HTTPException(422, "Unknown component")
        if key in chosen:
            return
        chosen.add(key)
        for dep in available[key].get("dependsOn", []):
            include(dep)

    for key in components or []:
        include(key)
    ingredient_indexes = sorted({i for key in chosen for i in available[key].get("ingredientIndexes", [])}) if chosen else list(range(len(out.get("recipeIngredient", []))))
    step_indexes = sorted({i for key in chosen for i in available[key].get("stepIndexes", [])}) if chosen else list(range(len(out.get("recipeInstructions", []))))
    out["recipeIngredient"] = [dict(out["recipeIngredient"][i], quantity=round(out["recipeIngredient"][i].get("quantity", 0) * factor, 4)) for i in ingredient_indexes]
    out["recipeInstructions"] = [out["recipeInstructions"][i] for i in step_indexes]
    out["recipeServings"] *= factor
    out["cooking"] = {"factor": factor, "components": sorted(chosen), "ingredientIndexes": ingredient_indexes,
                      "stepIndexes": step_indexes, "nutrition": calculate_nutrition(document, ingredient_indexes, factor),
                      "notice": "Cooking temperatures and times stay unchanged when scaling."}
    return out
