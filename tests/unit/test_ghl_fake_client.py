from __future__ import annotations

import pytest

from nurture.ghl import Contact, FakeGHLClient, GHLNotFoundError


@pytest.fixture
def fake_client() -> FakeGHLClient:
    contact = Contact(
        id="c1",
        first_name="Rahul",
        city="Pune",
        tags={"wa-stage-1"},
        fields={"wa_aum": None},
    )
    return FakeGHLClient(
        contacts={"c1": contact},
        threads={"c1": []},
        field_ids={"wa_aum": "field-id-1", "wa_years_in_business": "field-id-2"},
    )


async def test_get_contact_returns_a_copy_not_the_stored_object(fake_client):
    contact = await fake_client.get_contact("c1")
    contact.tags.add("mutated")
    stored = await fake_client.get_contact("c1")
    assert "mutated" not in stored.tags


async def test_get_contact_unknown_id_raises_not_found(fake_client):
    with pytest.raises(GHLNotFoundError):
        await fake_client.get_contact("nope")


async def test_send_whatsapp_appends_outbound_message_marked_sent_by_service(fake_client):
    message_id = await fake_client.send_whatsapp("c1", "hi there")
    thread = await fake_client.get_thread("c1")
    assert len(thread) == 1
    assert thread[0].id == message_id
    assert thread[0].direction == "outbound"
    assert thread[0].text == "hi there"
    assert thread[0].sent_by_service is True


async def test_add_note_is_recorded(fake_client):
    await fake_client.add_note("c1", "shadow mode note")
    assert fake_client.notes["c1"] == ["shadow mode note"]


async def test_set_tags_adds_and_removes(fake_client):
    await fake_client.set_tags("c1", add=["wa-stage-2"], remove=["wa-stage-1"])
    contact = await fake_client.get_contact("c1")
    assert contact.tags == {"wa-stage-2"}


async def test_update_custom_fields_sets_values(fake_client):
    await fake_client.update_custom_fields("c1", {"wa_aum": "6 crore"})
    contact = await fake_client.get_contact("c1")
    assert contact.fields["wa_aum"] == "6 crore"


async def test_update_custom_fields_raises_for_unresolved_key(fake_client):
    with pytest.raises(Exception):
        await fake_client.update_custom_fields("c1", {"wa_unregistered_key": "x"})


async def test_resolve_custom_field_ids_only_returns_known_keys(fake_client):
    result = await fake_client.resolve_custom_field_ids(["wa_aum", "wa_not_registered"])
    assert result == {"wa_aum": "field-id-1"}


async def test_get_thread_respects_limit(fake_client):
    for i in range(5):
        await fake_client.send_whatsapp("c1", f"msg {i}")
    thread = await fake_client.get_thread("c1", limit=2)
    assert len(thread) == 2
    assert [m.text for m in thread] == ["msg 3", "msg 4"]


async def test_every_call_is_recorded(fake_client):
    await fake_client.get_contact("c1")
    await fake_client.get_thread("c1")
    await fake_client.send_whatsapp("c1", "x")
    await fake_client.add_note("c1", "note")
    await fake_client.set_tags("c1", add=[], remove=[])
    await fake_client.update_custom_fields("c1", {})
    await fake_client.resolve_custom_field_ids([])

    recorded_methods = [call.method for call in fake_client.calls]
    assert recorded_methods == [
        "get_contact",
        "get_thread",
        "send_whatsapp",
        "add_note",
        "set_tags",
        "update_custom_fields",
        "resolve_custom_field_ids",
    ]
