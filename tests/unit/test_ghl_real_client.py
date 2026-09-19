from __future__ import annotations

import json

import httpx
import pytest
import respx

from nurture.ghl import GHLAuthError, GHLNotFoundError, RealGHLClient

BASE_URL = "https://api.test.example"
API_VERSION = "2021-07-28"
LOCATION_ID = "FlT9bndDcWIrmuveZWZa"
CONTACT_ID = "PkciBJMS9v7ujtGvvsyA"


@pytest.fixture
async def client():
    c = RealGHLClient(
        base_url=BASE_URL, api_version=API_VERSION, token="test-token", location_id=LOCATION_ID
    )
    yield c
    await c.aclose()


def _custom_fields_route(router, load_ghl_fixture, fixture_name: str = "get_custom_fields.json"):
    router.get(f"{BASE_URL}/locations/{LOCATION_ID}/customFields").mock(
        return_value=httpx.Response(200, json=load_ghl_fixture(fixture_name))
    )


async def test_get_contact_parses_real_fixture_with_no_wa_fields_resolved(
    client, load_ghl_fixture
):
    with respx.mock:
        _custom_fields_route(respx, load_ghl_fixture)
        respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(200, json=load_ghl_fixture("get_contact.json"))
        )
        contact = await client.get_contact(CONTACT_ID)

    assert contact.id == CONTACT_ID
    assert contact.first_name == "Test"
    # None of our 12 wa_* fields exist live yet (docs/phase0-findings.md),
    # so none should resolve onto the contact.
    assert contact.fields == {}
    assert "26-09-2026 webinar registration" in contact.tags


async def test_get_contact_parses_wa_fields_once_they_exist(client, load_ghl_fixture):
    with respx.mock:
        _custom_fields_route(respx, load_ghl_fixture, "get_custom_fields_with_wa_fields.json")
        respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(
                200, json=load_ghl_fixture("get_contact_with_wa_fields.json")
            )
        )
        contact = await client.get_contact(CONTACT_ID)

    assert contact.fields["wa_aum"] == "6 crore"
    assert contact.fields["wa_years_in_business"] == "3 years"
    assert contact.fields["wa_bot_turns"] == "2"
    assert contact.city == "Pune"


async def test_custom_fields_are_only_fetched_once_across_calls(client, load_ghl_fixture):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/locations/{LOCATION_ID}/customFields").mock(
            return_value=httpx.Response(200, json=load_ghl_fixture("get_custom_fields.json"))
        )
        respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(200, json=load_ghl_fixture("get_contact.json"))
        )
        await client.get_contact(CONTACT_ID)
        await client.get_contact(CONTACT_ID)
        await client.resolve_custom_field_ids(["wa_aum"])

    assert route.call_count == 1


async def test_get_thread_parses_real_fixture_oldest_first(client, load_ghl_fixture):
    with respx.mock:
        respx.get(f"{BASE_URL}/conversations/messages/export").mock(
            return_value=httpx.Response(200, json=load_ghl_fixture("list_messages.json"))
        )
        messages = await client.get_thread(CONTACT_ID)

    assert len(messages) == 2
    assert messages[0].direction == "inbound"
    assert messages[0].text == "I wanted to learn more about OAWA."
    assert messages[1].direction == "outbound"
    # oldest first: the inbound message (18:32:22) precedes the outbound reply (18:32:24)
    assert messages[0].sent_at < messages[1].sent_at


async def test_get_thread_parses_synthetic_whatsapp_fixture(client, load_ghl_fixture):
    with respx.mock:
        respx.get(f"{BASE_URL}/conversations/messages/export").mock(
            return_value=httpx.Response(
                200, json=load_ghl_fixture("list_messages_whatsapp_synthetic.json")
            )
        )
        messages = await client.get_thread(CONTACT_ID)

    assert [m.text for m in messages] == [
        "around 6 crore abhi",
        "Got it — and how many years have you been in business?",
    ]


async def test_send_whatsapp_returns_message_id_from_verified_schema(client, load_ghl_fixture):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/conversations/messages").mock(
            return_value=httpx.Response(
                200, json=load_ghl_fixture("send_whatsapp_response.json")
            )
        )
        message_id = await client.send_whatsapp(CONTACT_ID, "hello")

    assert message_id == "sentmsg0000000000000001"
    sent_body = route.calls.last.request.content
    assert json.loads(sent_body) == {
        "type": "WhatsApp",
        "contactId": CONTACT_ID,
        "message": "hello",
    }


async def test_add_note_posts_body_and_does_not_raise(client, load_ghl_fixture):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/contacts/{CONTACT_ID}/notes").mock(
            return_value=httpx.Response(201, json=load_ghl_fixture("create_note_response.json"))
        )
        await client.add_note(CONTACT_ID, "shadow mode note")

    assert route.called


async def test_set_tags_adds_and_removes_via_separate_calls(client, load_ghl_fixture):
    with respx.mock:
        add_route = respx.post(f"{BASE_URL}/contacts/{CONTACT_ID}/tags").mock(
            return_value=httpx.Response(201, json=load_ghl_fixture("add_tags_response.json"))
        )
        remove_route = respx.delete(f"{BASE_URL}/contacts/{CONTACT_ID}/tags").mock(
            return_value=httpx.Response(200, json=load_ghl_fixture("remove_tags_response.json"))
        )
        await client.set_tags(CONTACT_ID, add=["wa-stage-2"], remove=["wa-stage-1"])

    assert add_route.called
    assert remove_route.called


async def test_set_tags_skips_call_when_list_is_empty(client, load_ghl_fixture):
    with respx.mock:
        add_route = respx.post(f"{BASE_URL}/contacts/{CONTACT_ID}/tags").mock(
            return_value=httpx.Response(201, json=load_ghl_fixture("add_tags_response.json"))
        )
        await client.set_tags(CONTACT_ID, add=[], remove=[])

    assert not add_route.called


async def test_update_custom_fields_resolves_ids_and_sends_correct_payload(
    client, load_ghl_fixture
):
    with respx.mock:
        _custom_fields_route(respx, load_ghl_fixture, "get_custom_fields_with_wa_fields.json")
        route = respx.put(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(
                200, json=load_ghl_fixture("update_contact_response.json")
            )
        )
        await client.update_custom_fields(CONTACT_ID, {"wa_aum": "6 crore"})

    sent = json.loads(route.calls.last.request.content)
    assert sent == {"customFields": [{"id": "syn0001wa_aum000000000", "fieldValue": "6 crore"}]}


async def test_update_custom_fields_raises_when_field_not_yet_created(client, load_ghl_fixture):
    with respx.mock:
        _custom_fields_route(respx, load_ghl_fixture, "get_custom_fields.json")  # no wa_* here
        with pytest.raises(Exception):
            await client.update_custom_fields(CONTACT_ID, {"wa_aum": "6 crore"})


async def test_resolve_custom_field_ids_ignores_unrelated_near_miss_field(
    client, load_ghl_fixture
):
    with respx.mock:
        _custom_fields_route(respx, load_ghl_fixture, "get_custom_fields_with_wa_fields.json")
        resolved = await client.resolve_custom_field_ids(["wa_aum"])

    # contact.wa_group_joined must never be mistaken for one of our keys.
    assert resolved == {"wa_aum": "syn0001wa_aum000000000"}


async def test_401_raises_auth_error_without_retry(client, load_ghl_fixture):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(401, json={"message": "unauthorized"})
        )
        _custom_fields_route(respx, load_ghl_fixture)
        with pytest.raises(GHLAuthError):
            await client.get_contact(CONTACT_ID)

    assert route.call_count == 1


async def test_404_raises_not_found_without_retry(client, load_ghl_fixture):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/contacts/{CONTACT_ID}").mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )
        _custom_fields_route(respx, load_ghl_fixture)
        with pytest.raises(GHLNotFoundError):
            await client.get_contact(CONTACT_ID)

    assert route.call_count == 1
