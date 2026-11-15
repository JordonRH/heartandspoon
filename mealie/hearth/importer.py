"""Bounded public-web importing with DNS pinned before opening a connection."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str):
        super().__init__(hostname, timeout=12)
        self.address = address

    def connect(self) -> None:
        sock = socket.create_connection((self.address, 443), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


def public_html(url: str) -> str:
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443) or len(url) > 2048:
            raise HTTPException(422, "Import a public HTTPS recipe URL")
        try:
            addresses = list({item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)})
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise HTTPException(422, "Private and internal addresses cannot be imported")
            connection = PinnedHTTPS(parsed.hostname, addresses[0])
            try:
                target = parsed.path or "/"
                if parsed.query:
                    target += "?" + parsed.query
                connection.request("GET", target, headers={"User-Agent": "HearthAndSpoon/1.0 recipe importer", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.getheader("Location", ""))
                    continue
                if response.status != 200 or "html" not in response.getheader("Content-Type", "").lower():
                    raise HTTPException(422, "The website did not return a recipe page")
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise HTTPException(422, "Page exceeds the import size limit")
                return content.decode("utf-8", errors="replace")
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise HTTPException(422, "Could not fetch that recipe. Paste its text instead.") from error
    raise HTTPException(422, "Too many website redirects")


def import_url(url: str) -> dict:
    from recipe_scrapers import scrape_html
    content = public_html(url)
    try:
        scraper = scrape_html(content, org_url=url)
        ingredients = scraper.ingredients()
        instructions = scraper.instructions_list()
        try:
            minutes = scraper.total_time()
        except Exception:
            minutes = None
        return {"name": scraper.title(), "recipeServings": 1,
                "recipeIngredient": [{"note": line, "quantity": 0} for line in ingredients],
                "recipeInstructions": [{"text": line} for line in instructions],
                "totalTime": f"{minutes} min" if minutes else None, "orgURL": url,
                "extras": {"hearth": {"importNotes": "Review servings, quantities, units and nutrition before locking."}}}
    except Exception as error:
        raise HTTPException(422, "No supported recipe found. Paste the recipe text instead.") from error
