from __future__ import annotations

import httpx
import pytest
import respx

from nurture.ghl import GHLRateLimitedError, RealGHLClient
from nurture.ghl.real import MAX_RETRIES

BASE_URL = "https://api.test.example"
CONTACT_ID = "c1"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Retries would otherwise really sleep with exponential backoff; the
    retry *logic* (attempt counts, header handling) is what these tests
    check, not wall-clock timing, so make asyncio.sleep instant."""

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr("nurture.ghl.real.asyncio.sleep", fast_sleep)


@pytest.fixture
async def client():
    c = RealGHLClient(
        base_url=BASE_URL, api_version="2021-07-28", token="tok", location_id="loc1"
    )
    yield c
    await c.aclose()


async def test_429_is_retried_then_succeeds(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "0"}),
                httpx.Response(200, json={"contact": {"id": CONTACT_ID, "tags": []}}),
            ]
        )
        respx.get(f"{BASE_URL}/locations/loc1/customFields").mock(
            return_value=httpx.Response(200, json={"customFields": []})
        )
        contact = await client.get_contact(CONTACT_ID)

    assert contact.id == CONTACT_ID
    assert route.call_count == 2


async def test_500_is_retried_then_succeeds(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(502),
                httpx.Response(200, json={"contact": {"id": CONTACT_ID, "tags": []}}),
            ]
        )
        respx.get(f"{BASE_URL}/locations/loc1/customFields").mock(
            return_value=httpx.Response(200, json={"customFields": []})
        )
        contact = await client.get_contact(CONTACT_ID)

    assert contact.id == CONTACT_ID
    assert route.call_count == 3


async def test_retries_are_exhausted_after_max_retries(client):
    # 1 initial attempt + MAX_RETRIES retries, all 503, then give up.
    with respx.mock:
        route = respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(503)
        )
        respx.get(f"{BASE_URL}/locations/loc1/customFields").mock(
            return_value=httpx.Response(200, json={"customFields": []})
        )
        with pytest.raises(GHLRateLimitedError):
            await client.get_contact(CONTACT_ID)

    assert route.call_count == MAX_RETRIES + 1


async def test_retry_after_header_is_honoured(client, monkeypatch):
    seen_delays = []

    async def recording_sleep(seconds):
        seen_delays.append(seconds)

    monkeypatch.setattr("nurture.ghl.real.asyncio.sleep", recording_sleep)

    with respx.mock:
        respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, json={"contact": {"id": CONTACT_ID, "tags": []}}),
            ]
        )
        respx.get(f"{BASE_URL}/locations/loc1/customFields").mock(
            return_value=httpx.Response(200, json={"customFields": []})
        )
        await client.get_contact(CONTACT_ID)

    assert seen_delays == [7.0]


async def test_backoff_without_retry_after_header_grows_and_jitters(client, monkeypatch):
    seen_delays = []

    async def recording_sleep(seconds):
        seen_delays.append(seconds)

    monkeypatch.setattr("nurture.ghl.real.asyncio.sleep", recording_sleep)

    with respx.mock:
        respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, json={"contact": {"id": CONTACT_ID, "tags": []}}),
            ]
        )
        respx.get(f"{BASE_URL}/locations/loc1/customFields").mock(
            return_value=httpx.Response(200, json={"customFields": []})
        )
        await client.get_contact(CONTACT_ID)

    assert len(seen_delays) == 2
    # base=1.0 * 2**0=1.0 with up to 50% jitter, then base=1.0*2**1=2.0 with up to 50% jitter
    assert 1.0 <= seen_delays[0] <= 1.5
    assert 2.0 <= seen_delays[1] <= 3.0
