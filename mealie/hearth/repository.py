"""Scoped workflow repository and the atomic adapter into Mealie's recipe model."""
import json
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from mealie.db.models.recipe.recipe import RecipeModel
from mealie.db.models.recipe.ingredient import IngredientFoodModel, IngredientUnitModel
from mealie.db.models.recipe.category import Category
from mealie.db.models.recipe.tag import Tag
from mealie.db.models.recipe.tool import Tool
from slugify import slugify
from mealie.db.models.users.users import User
from mealie.hearth.models import Audit, CookSession, Draft, KitchenState, Revision
from mealie.schema.recipe.recipe import RecipeDraft


class KitchenRepository:
    def __init__(self, session: Session, owner: str):
        self.session = session
        self.owner = owner

    def owned(self, model: Any, key: str, lock: bool = False) -> Any:
        query = select(model).where(model.id == key, model.owner == self.owner)
        row = self.session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise HTTPException(404, "Not found")
        return row

    def rows(self, model: Any) -> list[Any]:
        return list(self.session.scalars(select(model).where(model.owner == self.owner).order_by(model.created_at.desc()).limit(1000)))

    def event(self, action: str, target: str) -> None:
        self.session.add(Audit(owner=self.owner, action=action, target=target))

    def write_mealie(self, document: dict, recipe_id: str) -> None:
        user = self.session.get(User, UUID(self.owner))
        if user is None:
            raise HTTPException(401, "Account unavailable")
        native = RecipeDraft.model_validate(document).model_dump()
        native.update(id=UUID(recipe_id), user_id=user.id, group_id=user.group_id,
                      household_id=user.household_id, slug=f"hearth-{recipe_id}")
        # The published snapshot contains display data, never live external references.
        def detach(value: Any) -> Any:
            if isinstance(value, list):
                return [detach(v) for v in value]
            if isinstance(value, dict):
                return {k: detach(v) for k, v in value.items() if k not in {"id", "group_id", "household_id", "user_id", "referenced_recipe", "substitutions", "households_with_ingredient_food", "households_with_tool"}}
            return value
        for key in ("recipe_ingredient", "tags", "tools", "recipe_category"):
            native[key] = detach(native.get(key, []))
        for key, model in (("tags", Tag), ("tools", Tool), ("recipe_category", Category)):
            resolved = []
            seen = set()
            for item in native[key]:
                slug = slugify(item["name"])
                if slug in seen:
                    continue
                seen.add(slug)
                match = self.session.scalar(select(model).where(model.group_id == user.group_id, model.slug == slug))
                if not match:
                    match = model(session=self.session, name=item["name"], group_id=user.group_id)
                    self.session.add(match)
                    self.session.flush()
                resolved.append({"id": match.id})
            native[key] = resolved
        for ingredient in native.get("recipe_ingredient", []):
            for key, model in (("food", IngredientFoodModel), ("unit", IngredientUnitModel)):
                if ingredient.get(key):
                    values = ingredient[key]
                    match = self.session.scalar(select(model).where(model.group_id == user.group_id, model.name == values["name"]))
                    if not match:
                        match = model(session=self.session, **{**values, "group_id": user.group_id})
                        self.session.add(match)
                        self.session.flush()
                    ingredient[key] = {"id": match.id}
        # Attachments are stored immutably by the kitchen, not in Mealie's mutable asset directory.
        native["assets"] = []
        native["image"] = None
        native["comments"] = []
        native["extras"] = {key: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
                            for key, value in native.get("extras", {}).items()}
        existing = self.session.get(RecipeModel, UUID(recipe_id))
        if existing:
            if str(existing.user_id) != self.owner:
                raise HTTPException(403, "Owner mismatch")
            existing.update(session=self.session, **native)
        else:
            self.session.add(RecipeModel(session=self.session, **native))
        self.session.flush()

    def publish(self, draft: Draft, commit: bool = True) -> Revision:
        recipe_id = draft.recipe_id or str(uuid4())
        state = self.owned(KitchenState, recipe_id, lock=True) if draft.recipe_id else None
        if state and state.revision != draft.base_revision:
            raise HTTPException(409, "Recipe changed. Prepare and review a new proposal.")
        previous = self.owned(Revision, state.revision) if state else None
        self.write_mealie(draft.document, recipe_id)
        revision = Revision(id=str(uuid4()), owner=self.owner, recipe_id=recipe_id,
                            number=previous.number + 1 if previous else 1,
                            document=draft.document, fingerprint=draft.fingerprint)
        self.session.add(revision)
        self.session.flush()
        if state:
            state.revision = revision.id
        else:
            self.session.add(KitchenState(id=recipe_id, owner=self.owner, revision=revision.id))
        draft.status = "published"
        draft.recipe_id = recipe_id
        self.event("published", revision.id)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return revision


def draft_out(row: Draft) -> dict:
    return {"id": row.id, "recipeId": row.recipe_id, "baseRevision": row.base_revision,
            "document": row.document, "hash": row.fingerprint, "status": row.status,
            "reviewed": row.reviewed_at is not None}


def revision_out(row: Revision) -> dict:
    return {"id": row.recipe_id, "revision": row.id, "version": row.number,
            "document": row.document, "hash": row.fingerprint}


def cooking_out(row: CookSession) -> dict:
    return {"id": row.id, "revision": row.revision, "selection": row.selection, "progress": row.progress}
