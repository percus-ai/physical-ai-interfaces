import asyncio
import os

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.services.realtime_events import get_realtime_event_bus
import interfaces_backend.services.session_control_events as session_control_events
from interfaces_backend.services.session_control_events import (
    SESSION_CONTROL_TOPIC,
    normalize_session_kind,
    publish_session_control_event,
    publish_session_control_event_safely,
    session_control_channel_key,
)


def test_session_control_channel_key_uses_global_for_blank_session_id():
    assert (
        session_control_channel_key(session_kind="recording", session_id="")
        == "recording:global"
    )


def test_normalize_session_kind_rejects_unknown_kind():
    try:
        normalize_session_kind("unknown")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Unsupported session_kind" in str(exc)


def test_publish_session_control_event_emits_payload():
    async def _run() -> None:
        key = session_control_channel_key(session_kind="recording", session_id="dataset-1")
        bus = get_realtime_event_bus()
        subscription = bus.subscribe(SESSION_CONTROL_TOPIC, key)
        try:
            await publish_session_control_event(
                session_kind="recording",
                action="session_stop",
                phase="completed",
                session_id="dataset-1",
                success=True,
                message="Recording session stopped",
            )
            event = await asyncio.wait_for(subscription.queue.get(), timeout=1.0)
            payload = event["payload"]
            assert payload["action"] == "session_stop"
            assert payload["phase"] == "completed"
            assert payload["success"] is True
            assert payload["session_id"] == "dataset-1"
        finally:
            subscription.close()

    asyncio.run(_run())


def test_publish_session_control_event_safely_swallows_publish_errors(monkeypatch):
    async def _raise_publish(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(session_control_events, "publish_session_control_event", _raise_publish)

    asyncio.run(
        publish_session_control_event_safely(
            session_kind="recording",
            action="session_stop",
            phase="failed",
            session_id="dataset-1",
            success=False,
            message="failed",
        )
    )
