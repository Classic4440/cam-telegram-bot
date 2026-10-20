from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.store import (
    PersistenceFailure,
    Store,
    SupabaseBackend,
    _database_error_details,
    _supabase_key_kind,
    build_store,
)


def _client_with_data(data):
    table = Mock()
    for method in ("select", "eq", "limit", "order", "upsert", "insert", "delete", "update"):
        getattr(table, method).return_value = table
    table.execute.return_value = SimpleNamespace(data=data)
    client = Mock()
    client.table.return_value = table
    return client, table


def test_profile_retrieval_and_upsert_use_store_contract() -> None:
    client, table = _client_with_data([{"user_id": 42, "timezone": "Africa/Kampala"}])
    backend = SupabaseBackend(client)

    assert backend.get_profile(42) == {"user_id": 42, "timezone": "Africa/Kampala"}
    table.eq.assert_called_with("user_id", 42)

    backend.upsert_profile(42, timezone="UTC", persona=None)
    table.upsert.assert_called_once_with(
        {"user_id": 42, "timezone": "UTC"},
        on_conflict="user_id",
    )


def test_notes_crud_uses_owner_scoped_queries() -> None:
    client, table = _client_with_data([{"id": 7, "user_id": 42, "body": "remember"}])
    backend = SupabaseBackend(client)

    assert backend.add_note(42, "remember")["body"] == "remember"
    table.insert.assert_called_once_with({"user_id": 42, "body": "remember"})

    assert backend.list_notes(42)[0]["id"] == 7
    assert table.eq.call_args_list[-1].args == ("user_id", 42)

    assert backend.delete_note(42, 7) is True
    assert table.eq.call_args_list[-2].args == ("user_id", 42)
    assert table.eq.call_args_list[-1].args == ("id", 7)


def test_xp_flush_uses_exact_named_rpc_contract() -> None:
    execute = Mock()
    rpc = Mock(return_value=Mock(execute=execute))
    backend = SupabaseBackend(Mock(rpc=rpc))

    backend.flush_xp({42: 7}, {42: "CamUser"})

    rpc.assert_called_once_with(
        "add_xp",
        {"p_user_id": 42, "p_username": "CamUser", "p_amount": 7},
    )
    execute.assert_called_once_with()


def test_partial_xp_flush_requeues_only_unconfirmed_users() -> None:
    first_execute = Mock()
    second_execute = Mock(side_effect=ConnectionError("network lost"))
    third_execute = Mock()
    client = Mock()
    client.rpc.side_effect = [
        Mock(execute=first_execute),
        Mock(execute=second_execute),
        Mock(execute=third_execute),
    ]

    async def run():
        store = Store(SupabaseBackend(client))
        store.add_xp(1, "first", 3)
        store.add_xp(2, "second", 5)

        assert await store.flush_xp() == 1
        assert store._xp == {2: 5}

        assert await store.flush_xp() == 1
        assert store._xp == {}

    asyncio.run(run())
    assert client.rpc.call_count == 3
    assert client.rpc.call_args_list[0].args[1]["p_user_id"] == 1
    assert client.rpc.call_args_list[1].args[1]["p_user_id"] == 2
    assert client.rpc.call_args_list[2].args[1]["p_user_id"] == 2


def test_transient_note_write_is_explicitly_memory_only() -> None:
    class FailingRemote:
        def add_note(self, user_id, body):
            raise ConnectionError("offline")

    async def run():
        store = Store(FailingRemote())
        with pytest.raises(PersistenceFailure) as result:
            await store.add_note(42, "remember")
        assert result.value.category == "transient"
        assert result.value.fallback_applied is True
        assert store.local.list_notes(42)[0]["body"] == "remember"

    asyncio.run(run())


def test_failed_xp_flush_is_requeued_without_memory_application_or_loss() -> None:
    class FailingRemote:
        def __init__(self):
            self.failed = True
            self.persisted = 0

        def flush_xp(self, deltas, names):
            if self.failed:
                raise ConnectionError("offline")
            self.persisted += sum(deltas.values())

    async def run():
        remote = FailingRemote()
        store = Store(remote)
        store.add_xp(42, "CamUser", 5)

        assert await store.flush_xp() == 0
        assert store._xp[42] == 5
        assert store.local.get_profile(42) is None

        remote.failed = False
        assert await store.flush_xp() == 1
        assert remote.persisted == 5
        assert store._xp[42] == 0

    asyncio.run(run())


def test_schema_and_permission_failures_do_not_fall_back_to_memory() -> None:
    class APIError(Exception):
        def __init__(self, code):
            super().__init__("provider error")
            self.code = code

    class FailingRemote:
        def __init__(self, code):
            self.code = code

        def add_note(self, user_id, body):
            raise APIError(self.code)

    async def run():
        for code, category in (("PGRST205", "schema"), ("42501", "permission")):
            store = Store(FailingRemote(code))
            with pytest.raises(PersistenceFailure) as result:
                await store.add_note(42, "do not persist locally")
            assert result.value.category == category
            assert store.local.list_notes(42) == []

    asyncio.run(run())


def test_error_classification_distinguishes_schema_permission_and_outage() -> None:
    class APIError(Exception):
        def __init__(self, code=None, status_code=None):
            super().__init__("request failed")
            self.code = code
            self.status_code = status_code

    assert _database_error_details(APIError("PGRST202"))[0] == "schema"
    assert _database_error_details(APIError("42501"))[0] == "permission"
    assert _database_error_details(APIError(status_code=503))[0] == "transient"
    assert _database_error_details(ValueError("bad query"))[0] == "database"


def test_store_requires_server_side_key_and_does_not_log_it() -> None:
    def jwt(payload):
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"

    assert _supabase_key_kind(jwt({"role": "service_role"})) == "service-role"
    assert _supabase_key_kind(jwt({"role": "anon"})) == "public"
    with pytest.raises(RuntimeError, match="public/anon"):
        build_store("https://example.supabase.co", jwt({"role": "anon"}))
    assert build_store(None, None).durable is False
