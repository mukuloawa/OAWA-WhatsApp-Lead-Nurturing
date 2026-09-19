"""RealGHLClient: the only code that makes real GHL/Synamate HTTP calls.

Endpoints and response shapes below are exactly what was verified
read-only (or schema-only, for writes) against the real OAWA Synamate
account in Phase 0/2 — see docs/phase0-findings.md §1 and §6. Nothing
here was guessed.

One real deviation from DESIGN.md Section 7.2's expected endpoint list:
DESIGN.md expected "List messages" to be `GET /conversations/{id}/messages`.
That operation does not exist in the verified GHL v2 API surface. The
verified alternative — confirmed via schema and one real read-only call
in Phase 2 — is `GET /conversations/messages/export`, filtered by
`contactId`, which returns the same kind of message list. get_thread()
uses that instead.

GHL_BASE_URL / GHL_API_VERSION: DESIGN.md marks these [VERIFY]. Phase 0/2
could not observe the literal HTTP headers directly (calls went through
an already-configured connection that handled them internally), so these
remain configured defaults rather than independently confirmed values —
see docs/phase0-findings.md §2. They are read from Settings, not
hardcoded, specifically because they are not fully verified.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

import httpx

from nurture.ghl.client import GHLClient
from nurture.ghl.errors import GHLAuthError, GHLError, GHLNotFoundError, GHLRateLimitedError
from nurture.ghl.fields import from_ghl_field_key
from nurture.ghl.models import Contact, Message

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0


class RealGHLClient(GHLClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_version: str,
        token: str,
        location_id: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._location_id = location_id
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Version": api_version,
                "Accept": "application/json",
            },
        )
        # id -> our bare key (e.g. "wa_aum"), populated lazily by
        # _ensure_field_map(). Resolving once and caching avoids a
        # customFields call on every single contact/update operation.
        self._field_key_by_id: dict[str, str] | None = None
        self._field_id_by_key: dict[str, str] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- internal: retrying request helper -----------------------------

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            response = await self._client.request(method, path, **kwargs)

            if response.status_code in (401, 403):
                raise GHLAuthError(
                    f"{method} {path} -> {response.status_code}: check GHL token/scopes"
                )
            if response.status_code == 404:
                raise GHLNotFoundError(f"{method} {path} -> 404")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    raise GHLRateLimitedError(
                        f"{method} {path} -> {response.status_code} after {attempt} retries"
                    )
                delay = self._backoff_delay(attempt, response)
                await asyncio.sleep(delay)
                attempt += 1
                continue

            response.raise_for_status()
            return response

    @staticmethod
    def _backoff_delay(attempt: int, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
        base = BASE_BACKOFF_SECONDS * (2**attempt)
        jitter = random.uniform(0, base * 0.5)
        return base + jitter

    # --- custom field resolution -----------------------------------------

    async def _ensure_field_map(self) -> None:
        if self._field_key_by_id is not None:
            return
        response = await self._request(
            "GET", f"/locations/{self._location_id}/customFields"
        )
        body = response.json()
        key_by_id: dict[str, str] = {}
        id_by_key: dict[str, str] = {}
        for field in body.get("customFields", []):
            our_key = from_ghl_field_key(field.get("fieldKey", ""))
            if our_key is not None:
                key_by_id[field["id"]] = our_key
                id_by_key[our_key] = field["id"]
        self._field_key_by_id = key_by_id
        self._field_id_by_key = id_by_key

    async def resolve_custom_field_ids(self, keys: list[str]) -> dict[str, str]:
        await self._ensure_field_map()
        assert self._field_id_by_key is not None
        return {key: self._field_id_by_key[key] for key in keys if key in self._field_id_by_key}

    # --- GHLClient protocol -----------------------------------------------

    async def get_contact(self, contact_id: str) -> Contact:
        await self._ensure_field_map()
        assert self._field_key_by_id is not None

        response = await self._request("GET", f"/contacts/{contact_id}")
        raw = response.json()["contact"]

        fields: dict[str, str | None] = {}
        for cf in raw.get("customFields", []):
            our_key = self._field_key_by_id.get(cf.get("id", ""))
            if our_key is not None:
                fields[our_key] = cf.get("value")

        return Contact(
            id=raw["id"],
            first_name=raw.get("firstName"),
            city=raw.get("city"),
            tags=set(raw.get("tags", [])),
            fields=fields,
        )

    async def get_thread(self, contact_id: str, limit: int = 50) -> list[Message]:
        response = await self._request(
            "GET",
            "/conversations/messages/export",
            params={
                "contactId": contact_id,
                "limit": limit,
                "sortBy": "createdAt",
                "sortOrder": "desc",
            },
        )
        raw_messages = response.json().get("messages", [])

        messages = [
            Message(
                id=m["id"],
                direction=m["direction"],
                text=m.get("body") or "",
                sent_at=datetime.fromisoformat(m["dateAdded"].replace("Z", "+00:00")),
                sent_by_service=False,  # adapter has no DB access; caller must set this
            )
            for m in raw_messages
        ]
        return list(reversed(messages))  # oldest first

    async def send_whatsapp(self, contact_id: str, text: str) -> str:
        response = await self._request(
            "POST",
            "/conversations/messages",
            json={"type": "WhatsApp", "contactId": contact_id, "message": text},
        )
        body = response.json()
        message_id = body.get("messageId")
        if not message_id:
            message_ids = body.get("messageIds") or []
            message_id = message_ids[0] if message_ids else None
        if not message_id:
            raise GHLError(f"send_whatsapp: no messageId in response: {body}")
        return message_id

    async def add_note(self, contact_id: str, text: str) -> None:
        await self._request("POST", f"/contacts/{contact_id}/notes", json={"body": text})

    async def set_tags(self, contact_id: str, add: list[str], remove: list[str]) -> None:
        if add:
            await self._request(
                "POST", f"/contacts/{contact_id}/tags", json={"tags": add}
            )
        if remove:
            await self._request(
                "DELETE", f"/contacts/{contact_id}/tags", json={"tags": remove}
            )

    async def update_custom_fields(self, contact_id: str, fields: dict[str, str]) -> None:
        ids_by_key = await self.resolve_custom_field_ids(list(fields.keys()))
        missing = [key for key in fields if key not in ids_by_key]
        if missing:
            raise GHLError(
                f"update_custom_fields: no GHL field id resolved for keys {missing} "
                "(field not yet created in GHL — see docs/phase0-findings.md §4)"
            )
        payload = [
            {"id": ids_by_key[key], "fieldValue": value} for key, value in fields.items()
        ]
        await self._request(
            "PUT", f"/contacts/{contact_id}", json={"customFields": payload}
        )
