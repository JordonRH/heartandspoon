"""Synthetic-only integration tests; run against a disposable database."""
import copy
import hashlib
import re
import time
import unittest
from base64 import urlsafe_b64encode
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from mealie.core.security import hash_password
from mealie.db.db_setup import session_context
from mealie.db.models.recipe.recipe import RecipeModel
from mealie.db.models.users.users import User
from mealie.hearth.app import app
from mealie.hearth.auth import PUBLIC_URL
from mealie.hearth.domain import cooking_view, validate
from mealie.hearth.importer import public_html
from mealie.hearth.mcp import actor, identity, server
from mealie.hearth.models import Audit, Draft, Revision

PASSWORD = "synthetic-kitchen-password-1234"
EMAIL = "synthetic@example.invalid"
HEADERS = {"Origin": PUBLIC_URL, "X-Hearth-Request": "1"}


def sample(name: str = "Synthetic tomato pasta") -> dict:
    return {"name": name, "description": "SYNTHETIC TEST DATA", "recipeServings": 4,
            "prepTime": "10 min", "performTime": "20 min", "totalTime": "30 min",
            "recipeIngredient": [
                {"quantity": 200, "unit": {"name": "g"}, "food": {"name": "tomatoes"}, "note": "chopped"},
                {"quantity": 400, "unit": {"name": "g"}, "food": {"name": "pasta"}}],
            "recipeInstructions": [{"text": "Prepare the sauce.", "durationSeconds": 300}, {"text": "Cook pasta and combine."}],
            "tags": [{"name": "Weeknight"}], "tools": [{"name": "Hob"}],
            "extras": {"hearth": {"components": [{"id": "sauce", "name": "Sauce", "ingredientIndexes": [0], "stepIndexes": [0], "dependsOn": []}],
                                  "ingredientNutrition": [
                                      {"index": 0, "per100g": {"calories": 20, "protein": 1}, "source": "synthetic label"},
                                      {"index": 1, "per100g": {"calories": 100, "protein": 5}, "source": "synthetic label"}]}}}


def configure_fixture() -> str:
    with session_context() as session:
        user = session.scalar(select(User).where(User.admin == True).limit(1))  # noqa E712
        user.username = EMAIL
        user.email = EMAIL
        user.full_name = "Synthetic Cook"
        user.password = hash_password(PASSWORD)
        session.add(Audit(owner=str(user.id), action="owner_configured", target=str(user.id)))
        session.commit()
        return str(user.id)


class KitchenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = TestClient(app, base_url=PUBLIC_URL)
        cls.client = cls.context.__enter__()
        cls.owner = configure_fixture()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.__exit__(None, None, None)

    def setUp(self) -> None:
        from sqlalchemy import delete
        from mealie.hearth.models import Limit
        with session_context() as session:
            session.execute(delete(Limit))
            session.commit()
        self.client.cookies.clear()
        result = self.client.post("/api/kitchen/login", json={"username": EMAIL, "password": PASSWORD}, headers=HEADERS)
        self.assertEqual(result.status_code, 200)
        self.assertIn("HttpOnly", result.headers["set-cookie"])
        self.assertIn("Secure", result.headers["set-cookie"])

    def draft(self, recipe_id: str | None = None, document: dict | None = None) -> dict:
        response = self.client.post("/api/kitchen/drafts", json={"document": document or sample(), "recipeId": recipe_id}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def publish(self, draft: dict) -> dict:
        response = self.client.post(f'/api/kitchen/drafts/{draft["id"]}/publish', json={"hash": draft["hash"], "password": PASSWORD}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def review(self, draft: dict) -> None:
        result = self.client.post(f'/api/kitchen/drafts/{draft["id"]}/review', json={"hash": draft["hash"]}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)

    def test_recipe_is_native_and_history_is_immutable(self) -> None:
        recipe = self.publish(self.draft())
        with session_context() as session:
            from uuid import UUID
            native = session.get(RecipeModel, UUID(recipe["id"]))
            self.assertEqual(native.name, recipe["document"]["name"])
            self.assertEqual(len(native.recipe_ingredient), 2)
            with self.assertRaises(DatabaseError):
                session.execute(text("UPDATE hearth_revisions SET number=999 WHERE id=:id"), {"id": recipe["revision"]})
                session.commit()
            session.rollback()

    def test_two_confirmations_and_reauthentication(self) -> None:
        original = self.publish(self.draft())
        doc = copy.deepcopy(original["document"])
        doc["name"] = "Synthetic revised pasta"
        proposal = self.draft(original["id"], doc)
        route = f'/api/kitchen/drafts/{proposal["id"]}/publish'
        self.assertEqual(self.client.post(route, json={"hash": proposal["hash"], "password": PASSWORD}, headers=HEADERS).status_code, 409)
        self.review(proposal)
        self.assertEqual(self.client.post(route, json={"hash": proposal["hash"], "password": "wrong"}, headers=HEADERS).status_code, 401)
        revised = self.publish(proposal)
        self.assertEqual(revised["version"], 2)
        self.assertEqual(self.client.post(route, json={"hash": proposal["hash"], "password": PASSWORD}, headers=HEADERS).status_code, 409)
        versions = self.client.get(f'/api/kitchen/recipes/{original["id"]}/versions').json()
        self.assertEqual(len(versions), 2)
        self.assertEqual(next(x for x in versions if x["version"] == 1)["document"]["name"], original["document"]["name"])

    def test_changed_draft_invalidates_review(self) -> None:
        recipe = self.publish(self.draft())
        proposal = self.draft(recipe["id"], recipe["document"])
        self.review(proposal)
        doc = copy.deepcopy(proposal["document"])
        doc["description"] = "Changed after confirmation"
        changed = self.client.put(f'/api/kitchen/drafts/{proposal["id"]}', json={"document": doc, "hash": proposal["hash"]}, headers=HEADERS).json()
        self.assertFalse(changed["reviewed"])
        self.assertEqual(self.client.post(f'/api/kitchen/drafts/{proposal["id"]}/publish', json={"hash": changed["hash"], "password": PASSWORD}, headers=HEADERS).status_code, 409)

    def test_expiry_session_binding_and_stale_base(self) -> None:
        recipe = self.publish(self.draft())
        proposal = self.draft(recipe["id"], recipe["document"])
        other = self.draft(recipe["id"], recipe["document"])
        self.review(proposal)
        with session_context() as session:
            session.get(Draft, proposal["id"]).reviewed_at = time.time() - 601
            session.commit()
        route = f'/api/kitchen/drafts/{proposal["id"]}/publish'
        self.assertEqual(self.client.post(route, json={"hash": proposal["hash"], "password": PASSWORD}, headers=HEADERS).status_code, 409)
        self.review(proposal)
        self.client.post('/api/kitchen/login', json={"username": EMAIL, "password": PASSWORD}, headers=HEADERS)
        self.assertEqual(self.client.post(route, json={"hash": proposal["hash"], "password": PASSWORD}, headers=HEADERS).status_code, 409)
        self.review(proposal)
        self.publish(proposal)
        self.assertEqual(self.client.post(f'/api/kitchen/drafts/{other["id"]}/review', json={"hash": other["hash"]}, headers=HEADERS).status_code, 409)

    def test_scaling_partial_recipe_and_pinned_session(self) -> None:
        recipe = self.publish(self.draft())
        result = self.client.post('/api/kitchen/cooking', json={"recipeId": recipe["id"], "factor": .5, "components": ["sauce"]}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        cook = result.json()
        self.assertEqual(len(cook["document"]["recipeIngredient"]), 1)
        self.assertEqual(cook["document"]["recipeIngredient"][0]["quantity"], 100)
        self.assertEqual(cook["document"]["cooking"]["nutrition"]["total"]["calories"], 20)
        self.assertEqual(cook["document"]["recipeInstructions"][0]["durationSeconds"], 300)
        changed = copy.deepcopy(recipe["document"])
        changed["recipeInstructions"][0]["text"] = "A new instruction"
        proposal = self.draft(recipe["id"], changed)
        self.review(proposal)
        self.publish(proposal)
        self.assertEqual(self.client.get('/api/kitchen/cooking/' + cook["id"]).json()["document"]["recipeInstructions"][0]["text"], "Prepare the sauce.")
        saved = self.client.put('/api/kitchen/cooking/' + cook["id"], json={"completed": [0]}, headers=HEADERS)
        self.assertEqual(saved.json()["progress"]["completed"], [0])

    def test_nutrition_calculates_and_reports_missing(self) -> None:
        doc = validate(sample())
        nutrition = doc["extras"]["hearth"]["nutrition"]
        self.assertTrue(nutrition["complete"])
        self.assertEqual(nutrition["total"]["calories"], 440)
        self.assertEqual(nutrition["perServing"]["calories"], 110)
        half = cooking_view(doc, .5)
        self.assertEqual(half["cooking"]["nutrition"]["total"]["calories"], 220)
        self.assertEqual(half["cooking"]["nutrition"]["perServing"]["calories"], 110)
        doc["recipeIngredient"][0]["unit"]["name"] = "cup"
        nutrition = validate(doc)["extras"]["hearth"]["nutrition"]
        self.assertFalse(nutrition["complete"])
        self.assertEqual(nutrition["missingIngredients"], [0])

    def test_request_ids_prevent_duplicate_ai_additions(self) -> None:
        payload = {"document": sample("Synthetic idempotency recipe"), "requestId": "synthetic-request-id"}
        first = self.client.post('/api/kitchen/drafts', json=payload, headers=HEADERS)
        second = self.client.post('/api/kitchen/drafts', json=payload, headers=HEADERS)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])
        payload['document']['name'] = 'Different content'
        self.assertEqual(self.client.post('/api/kitchen/drafts', json=payload, headers=HEADERS).status_code, 409)

    def test_components_and_ownership_validation(self) -> None:
        doc = sample()
        doc["extras"]["hearth"]["components"][0]["dependsOn"] = ["sauce"]
        self.assertEqual(self.client.post('/api/kitchen/drafts', json={"document": doc}, headers=HEADERS).status_code, 422)
        doc = sample()
        doc["extras"]["hearth"]["components"][0]["ingredientIndexes"] = [999]
        self.assertEqual(self.client.post('/api/kitchen/drafts', json={"document": doc}, headers=HEADERS).status_code, 422)
        from mealie.hearth.repository import KitchenRepository
        with session_context() as session:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                KitchenRepository(session, "someone-else").owned(Draft, self.draft()["id"])

    def test_no_upstream_write_bypass_and_csrf(self) -> None:
        self.assertEqual(self.client.post('/api/recipes', json={"name": "bypass"}, headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.post('/api/kitchen/drafts', json={"document": sample()}).status_code, 403)
        self.assertEqual(self.client.post('/api/kitchen/drafts', json={"document": sample()}, headers={**HEADERS, "Origin": "https://attacker.invalid"}).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/kitchen/recipes').status_code, 401)
        self.assertEqual(self.client.post('/api/kitchen/login', json={"username": "admin", "password": "MyPassword"}, headers=HEADERS).status_code, 401)

    def test_ssrf_private_dns_and_redirect_scheme_are_blocked(self) -> None:
        from fastapi import HTTPException
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(HTTPException):
                public_html('https://example.invalid/recipe')
        with self.assertRaises(HTTPException):
            public_html('file:///etc/passwd')

    def test_photo_upload_and_theme_preference(self) -> None:
        import io
        from PIL import Image
        output = io.BytesIO()
        Image.new('RGB', (16, 16), color='green').save(output, format='PNG')
        photo = self.client.post('/api/kitchen/media', files={'file': ('synthetic.png', output.getvalue(), 'image/png')}, headers=HEADERS)
        self.assertEqual(photo.status_code, 200, photo.text)
        response = self.client.get(photo.json()['url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/webp')
        self.assertEqual(self.client.post('/api/kitchen/media', files={'file': ('bad.html', b'<script>bad</script>', 'text/html')}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.put('/api/kitchen/preferences', json={'theme': 'botanical'}, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get('/api/kitchen/me').json()['theme'], 'botanical')
        self.assertEqual(self.client.put('/api/kitchen/preferences', json={'theme': 'invalid'}, headers=HEADERS).status_code, 422)

    def test_oauth_pkce_rotation_scope_and_mcp_transport(self) -> None:
        callback = 'https://chatgpt.com/connector/oauth/synthetic-test'
        registration = self.client.post('/oauth/register', json={"redirect_uris": [callback]})
        self.assertEqual(registration.status_code, 201)
        client_id = registration.json()["client_id"]
        verifier = 'synthetic-pkce-verifier-' + 'x' * 30
        challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        resource = PUBLIC_URL + '/mcp/'
        query = dict(response_type='code', client_id=client_id, redirect_uri=callback, code_challenge=challenge,
                     code_challenge_method='S256', scope='recipes.read recipes.write', resource=resource, state='synthetic-state')
        page = self.client.get('/oauth/authorize', params=query)
        self.assertEqual(page.status_code, 200, page.text)
        nonce = re.search(r'name="consent" value="([^"]+)"', page.text)[1]
        consent = self.client.post('/oauth/authorize', data={"consent": nonce}, headers={"Origin": PUBLIC_URL}, follow_redirects=False)
        self.assertEqual(consent.status_code, 303)
        code = parse_qs(urlsplit(consent.headers['location']).query)['code'][0]
        form = dict(grant_type='authorization_code', client_id=client_id, redirect_uri=callback, code_verifier=verifier, code=code, resource=resource)
        self.assertEqual(self.client.post('/oauth/token', data={**form, 'code_verifier': 'bad'}).status_code, 400)
        tokens = self.client.post('/oauth/token', data=form).json()
        self.assertEqual(self.client.post('/oauth/token', data=form).status_code, 400)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        headers = {"Authorization": 'Bearer ' + tokens['access_token'], "Accept": 'application/json, text/event-stream'}
        self.client.cookies.clear()
        listed = self.client.post('/mcp/', json=request, headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        names = {tool['name'] for tool in listed.json()['result']['tools']}
        self.assertIn('create_recipe_draft', names)
        self.assertFalse(any('approve' in name or 'publish' in name for name in names))
        submitted = self.client.post('/mcp/', json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_recipe_draft", "arguments": {"document": sample("Synthetic MCP recipe")}}}, headers=headers)
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertFalse(submitted.json()['result'].get('isError'), submitted.text)
        self.assertEqual(self.client.post('/api/kitchen/drafts/invalid/review', json={}, headers={**HEADERS, **headers}).status_code, 401)
        self.assertEqual(self.client.post('/mcp/', json=request, headers={**headers, 'Authorization': 'Bearer ' + tokens['refresh_token']}).status_code, 401)
        refresh = dict(grant_type='refresh_token', client_id=client_id, refresh_token=tokens['refresh_token'], resource=resource)
        self.assertEqual(self.client.post('/oauth/token', data={**refresh, 'client_id': 'foreign'}).status_code, 400)
        self.assertEqual(self.client.post('/oauth/token', data=refresh).status_code, 200)
        self.assertEqual(self.client.post('/oauth/token', data=refresh).status_code, 400)
        context = identity.set((self.owner, {'recipes.read'}))
        try:
            self.assertEqual(actor(), self.owner)
            with self.assertRaises(ValueError):
                actor(True)
        finally:
            identity.reset(context)


if __name__ == '__main__':
    unittest.main()
