import copy
import time
from sqlalchemy import select

from fastapi import HTTPException

from mealie.hearth.domain import cooking_view, fingerprint, validate
from mealie.hearth.models import CookSession, Draft, KitchenState, Revision
from mealie.hearth.repository import KitchenRepository, cooking_out, draft_out, revision_out


class KitchenService:
    def __init__(self, repository: KitchenRepository):
        self.repo = repository

    def recipes(self, query: str = "") -> list[dict]:
        result = []
        for state in self.repo.rows(KitchenState):
            if state.archived:
                continue
            revision = self.repo.owned(Revision, state.revision)
            if query.lower() in str(revision.document).lower():
                result.append(revision_out(revision))
        return result

    def recipe(self, recipe_id: str) -> dict:
        state = self.repo.owned(KitchenState, recipe_id)
        return revision_out(self.repo.owned(Revision, state.revision))

    def create_draft(self, document: dict, recipe_id: str | None = None, request_id: str | None = None) -> dict:
        base = self.recipe(recipe_id) if recipe_id else None
        normalized = validate(document)
        request_hash = fingerprint(document)
        if request_id:
            if not isinstance(request_id, str) or len(request_id) > 120:
                raise HTTPException(422, "Request ID must be text up to 120 characters")
            existing = self.repo.session.scalar(select(Draft).where(Draft.owner == self.repo.owner, Draft.request_key == request_id))
            if existing:
                if existing.request_hash != request_hash or (recipe_id is not None and existing.recipe_id != recipe_id) or (recipe_id is None and existing.base_revision is not None):
                    raise HTTPException(409, "Request ID was already used for different content")
                return draft_out(existing)
        document = normalized
        row = Draft(owner=self.repo.owner, recipe_id=recipe_id, base_revision=base["revision"] if base else None,
                    document=document, fingerprint=fingerprint(document), request_key=request_id or None, request_hash=request_hash)
        self.repo.session.add(row)
        self.repo.session.flush()
        self.repo.event("draft_created", row.id)
        self.repo.session.commit()
        return draft_out(row)

    def update_draft(self, draft_id: str, document: dict, expected_hash: str) -> dict:
        row = self.repo.owned(Draft, draft_id, lock=True)
        if row.status != "draft" or row.fingerprint != expected_hash:
            raise HTTPException(409, "Draft changed or has already been published")
        row.document = validate(document)
        row.fingerprint = fingerprint(row.document)
        row.reviewed_at = None
        row.review_session = None
        self.repo.session.commit()
        return draft_out(row)

    def review(self, draft_id: str, expected_hash: str, browser_session: str) -> dict:
        row = self.repo.owned(Draft, draft_id, lock=True)
        if row.status != "draft" or row.fingerprint != expected_hash or fingerprint(row.document) != expected_hash:
            raise HTTPException(409, "Review the latest draft")
        if row.recipe_id and self.recipe(row.recipe_id)["revision"] != row.base_revision:
            raise HTTPException(409, "The original recipe changed. Create a fresh proposal.")
        row.reviewed_at = time.time()
        row.review_session = browser_session
        self.repo.event("review_confirmed", row.id)
        self.repo.session.commit()
        return draft_out(row)

    def publish(self, draft_id: str, expected_hash: str, browser_session: str) -> dict:
        row = self.repo.owned(Draft, draft_id, lock=True)
        if row.status != "draft" or row.fingerprint != expected_hash or fingerprint(row.document) != expected_hash:
            raise HTTPException(409, "Review the latest draft")
        if row.recipe_id and (not row.reviewed_at or time.time() - row.reviewed_at > 600 or row.review_session != browser_session):
            raise HTTPException(409, "First review confirmation is missing or expired")
        # New recipes need a human Save & lock. Established recipes require both steps.
        return revision_out(self.repo.publish(row))

    def review_many(self, items: list[dict], browser_session: str) -> list[dict]:
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise HTTPException(422, "Select between 1 and 100 recipe changes")
        ids = [item.get("id") for item in items if isinstance(item, dict)]
        if len(ids) != len(items) or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
            raise HTTPException(422, "Each selected change must be unique")
        hashes = {item["id"]: item.get("hash") for item in items}
        try:
            rows = [self.repo.owned(Draft, draft_id, lock=True) for draft_id in sorted(ids)]
            recipe_ids: set[str] = set()
            for row in rows:
                if (row.status != "draft" or not row.recipe_id or row.fingerprint != hashes[row.id]
                        or fingerprint(row.document) != row.fingerprint):
                    raise HTTPException(409, "A selected change is unavailable or has changed")
                if row.recipe_id in recipe_ids:
                    raise HTTPException(409, "Select only one change per recipe")
                recipe_ids.add(row.recipe_id)
                if self.recipe(row.recipe_id)["revision"] != row.base_revision:
                    raise HTTPException(409, "A selected recipe has changed. Prepare a fresh proposal.")
            reviewed_at = time.time()
            for row in rows:
                row.reviewed_at = reviewed_at
                row.review_session = browser_session
                self.repo.event("review_confirmed", row.id)
            self.repo.session.commit()
            return [draft_out(row) for row in rows]
        except Exception:
            self.repo.session.rollback()
            raise

    def publish_many(self, items: list[dict], browser_session: str) -> list[dict]:
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise HTTPException(422, "Select between 1 and 100 reviewed changes")
        ids = [item.get("id") for item in items if isinstance(item, dict)]
        if len(ids) != len(items) or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
            raise HTTPException(422, "Each selected change must be unique")
        hashes = {item["id"]: item.get("hash") for item in items}
        try:
            rows = [self.repo.owned(Draft, draft_id, lock=True) for draft_id in sorted(ids)]
            recipe_ids: set[str] = set()
            for row in rows:
                if (row.status != "draft" or not row.recipe_id or row.fingerprint != hashes[row.id]
                        or fingerprint(row.document) != row.fingerprint):
                    raise HTTPException(409, "A selected change is unavailable or has changed")
                if (not row.reviewed_at or time.time() - row.reviewed_at > 600
                        or row.review_session != browser_session):
                    raise HTTPException(409, "Review each selected change again before bulk approval")
                if row.recipe_id in recipe_ids:
                    raise HTTPException(409, "Select only one change per recipe")
                recipe_ids.add(row.recipe_id)
                if self.recipe(row.recipe_id)["revision"] != row.base_revision:
                    raise HTTPException(409, "A selected recipe has changed. Prepare and review a fresh proposal.")
            result = [revision_out(self.repo.publish(row, commit=False))
                      for row in sorted(rows, key=lambda item: item.recipe_id or "")]
            self.repo.session.commit()
            return result
        except Exception:
            self.repo.session.rollback()
            raise

    def start_cooking(self, recipe_id: str, factor: float, components: list[str], revision: str | None = None) -> dict:
        recipe = self.recipe(recipe_id)
        if revision:
            saved = self.repo.owned(Revision, revision)
            if saved.recipe_id != recipe_id:
                raise HTTPException(422, "Revision does not belong to this recipe")
            recipe = revision_out(saved)
        view = cooking_view(recipe["document"], factor, components)
        row = CookSession(owner=self.repo.owner, revision=recipe["revision"],
                          selection={"factor": factor, "components": components}, progress={})
        self.repo.session.add(row)
        self.repo.session.commit()
        return {**cooking_out(row), "document": view}

    def cooking(self, key: str) -> dict:
        row = self.repo.owned(CookSession, key)
        revision = self.repo.owned(Revision, row.revision)
        return {**cooking_out(row), "document": cooking_view(revision.document, **row.selection)}

    def progress(self, key: str, completed: list[int]) -> dict:
        row = self.repo.owned(CookSession, key, lock=True)
        view = self.cooking(key)["document"]
        if len(completed) > 1000 or any(type(i) is not int or i < 0 or i >= len(view["recipeInstructions"]) for i in completed):
            raise HTTPException(422, "Invalid completed steps")
        row.progress = {"completed": sorted(set(completed)), "updated": time.time()}
        self.repo.session.commit()
        return cooking_out(row)

    def variation(self, recipe_id: str, name: str) -> dict:
        original = self.recipe(recipe_id)
        doc = copy.deepcopy(original["document"])
        doc["name"] = name
        doc.setdefault("extras", {}).setdefault("hearth", {})["parent"] = {"recipeId": recipe_id, "revision": original["revision"]}
        return self.create_draft(doc)
