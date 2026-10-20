from __future__ import annotations

from unittest.mock import Mock

from bot.store import SupabaseBackend


def test_flush_xp_calls_add_xp_with_named_parameters() -> None:
    execute = Mock()
    rpc = Mock(return_value=Mock(execute=execute))
    backend = SupabaseBackend(Mock(rpc=rpc))

    backend.flush_xp({42: 7}, {42: "CamUser"})

    rpc.assert_called_once_with(
        "add_xp",
        {
            "p_user_id": 42,
            "p_username": "CamUser",
            "p_amount": 7,
        },
    )
    execute.assert_called_once_with()
