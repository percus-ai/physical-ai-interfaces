import asyncio

from interfaces_backend.services.realtime_events import RealtimeEventBus
from interfaces_backend.services.realtime_producers import RealtimeProducerHub


def test_realtime_producer_hub_shares_single_producer_and_stops_when_idle():
    async def _run() -> None:
        bus = RealtimeEventBus()
        hub = RealtimeProducerHub(bus)

        calls = {"count": 0}

        async def build_payload() -> dict:
            calls["count"] += 1
            return {"count": calls["count"]}

        sub_a = bus.subscribe("demo", "k1")
        sub_b = bus.subscribe("demo", "k1")
        await hub.publish_once(topic="demo", key="k1", build_payload=build_payload)
        hub.ensure_polling(
            topic="demo",
            key="k1",
            build_payload=build_payload,
            interval=0.01,
            idle_ttl=1.0,
        )
        hub.ensure_polling(
            topic="demo",
            key="k1",
            build_payload=build_payload,
            interval=0.01,
            idle_ttl=1.0,
        )

        assert len(hub._producers) == 1  # noqa: SLF001

        first_a = await asyncio.wait_for(sub_a.queue.get(), timeout=1.0)
        first_b = await asyncio.wait_for(sub_b.queue.get(), timeout=1.0)
        assert first_a["payload"]["count"] >= 1
        assert first_b["payload"]["count"] >= 1

        sub_a.close()
        sub_b.close()
        deadline = asyncio.get_running_loop().time() + 2.5
        while len(hub._producers) > 0 and asyncio.get_running_loop().time() < deadline:  # noqa: SLF001
            await asyncio.sleep(0.02)

        assert bus.subscriber_count("demo", "k1") == 0
        assert len(hub._producers) == 0  # noqa: SLF001

    asyncio.run(_run())
