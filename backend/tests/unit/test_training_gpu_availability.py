from types import SimpleNamespace

from interfaces_backend.api import training


class _DummyInstances:
    def __init__(self, responses: dict[bool, list[dict]]) -> None:
        self._responses = responses

    def get_availabilities(
        self, is_spot: bool | None = None, location_code: str | None = None
    ) -> list[dict]:
        return list(self._responses.get(bool(is_spot), []))


class _DummyLocations:
    def __init__(self, codes: list[str]) -> None:
        self._codes = codes

    def get(self) -> list[dict]:
        return [{"code": code} for code in self._codes]


class _DummyClient:
    def __init__(
        self,
        responses: dict[bool, list[dict]],
        instance_types: list[SimpleNamespace] | None = None,
        locations: list[str] | None = None,
    ) -> None:
        self.instances = _DummyInstances(responses)
        self.instance_types = SimpleNamespace(
            get=lambda: (
                instance_types
                or [
                    SimpleNamespace(
                        instance_type="1H100.80S.22V", spot_price_per_hour=2.0
                    ),
                ]
            )
        )
        self.locations = _DummyLocations(
            locations or ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]
        )


def test_fetch_availability_sets_parses_response_shape() -> None:
    client = _DummyClient(
        {
            True: [
                {"location_code": "FIN-01", "availabilities": ["1H100.80S.22V"]},
                {"location_code": "FIN-02", "availabilities": ["1A100.22V"]},
                {"location_code": "FIN-03", "availabilities": []},
                {"location_code": "ICE-01", "availabilities": ["1B200.180V"]},
            ],
            False: [
                {"location_code": "FIN-01", "availabilities": ["1H100.80S.22V"]},
                {"location_code": "FIN-02", "availabilities": ["1A100.22V"]},
            ],
        }
    )

    preferred_locations = ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]
    spot_by_loc, ondemand_by_loc = training._fetch_availability_sets(
        client, preferred_locations
    )  # noqa: SLF001

    assert spot_by_loc["FIN-01"] == {"1H100.80S.22V"}
    assert spot_by_loc["FIN-02"] == {"1A100.22V"}
    assert spot_by_loc["ICE-01"] == {"1B200.180V"}
    assert ondemand_by_loc["FIN-01"] == {"1H100.80S.22V"}
    assert ondemand_by_loc["FIN-02"] == {"1A100.22V"}


def test_get_gpu_availability_marks_instance_available(monkeypatch) -> None:
    client = _DummyClient(
        {
            True: [{"location_code": "FIN-01", "availabilities": ["1H100.80S.22V"]}],
            False: [],
        }
    )

    monkeypatch.setattr(training, "_get_verda_client", lambda: client)
    monkeypatch.setattr(training, "_gpu_availability_cache", {})
    monkeypatch.setattr(training, "_gpu_availability_cache_time", {})

    response = training.get_gpu_availability()

    h100 = next(item for item in response.available if item.gpu_model == "H100")
    assert h100.spot_available is True
    assert h100.ondemand_available is False
    assert h100.spot_locations == ["FIN-01"]


def test_get_gpu_availability_all_scan_returns_all_instance_types(monkeypatch) -> None:
    client = _DummyClient(
        {
            True: [
                {
                    "location_code": "FIN-01",
                    "availabilities": ["1H100.80S.22V", "2H100.80S.60V"],
                },
                {"location_code": "FIN-02", "availabilities": ["1A100.22V"]},
            ],
            False: [],
        },
        instance_types=[
            SimpleNamespace(instance_type="1H100.80S.22V", spot_price_per_hour=2.0),
            SimpleNamespace(instance_type="2H100.80S.60V", spot_price_per_hour=3.5),
            SimpleNamespace(instance_type="1A100.22V", spot_price_per_hour=1.0),
            SimpleNamespace(instance_type="CPU.16V.64G", spot_price_per_hour=0.0),
        ],
        locations=["FIN-01", "FIN-02", "FIN-03"],
    )

    monkeypatch.setattr(training, "_get_verda_client", lambda: client)
    monkeypatch.setattr(training, "_gpu_availability_cache", {})
    monkeypatch.setattr(training, "_gpu_availability_cache_time", {})

    response = training.get_gpu_availability(scan="all")
    by_instance_type = {item.instance_type: item for item in response.available}

    assert "1H100.80S.22V" in by_instance_type
    assert "2H100.80S.60V" in by_instance_type
    assert "1A100.22V" in by_instance_type
    assert "CPU.16V.64G" not in by_instance_type
    assert by_instance_type["2H100.80S.60V"].gpu_count == 2
    assert by_instance_type["1A100.22V"].spot_locations == ["FIN-02"]


def test_get_gpu_availability_defaults_to_all(monkeypatch) -> None:
    client = _DummyClient(
        {
            True: [
                {
                    "location_code": "FIN-01",
                    "availabilities": ["1H100.80S.22V", "2H100.80S.60V"],
                }
            ],
            False: [],
        },
        instance_types=[
            SimpleNamespace(instance_type="1H100.80S.22V", spot_price_per_hour=2.0),
            SimpleNamespace(instance_type="2H100.80S.60V", spot_price_per_hour=3.5),
        ],
        locations=["FIN-01"],
    )

    monkeypatch.setattr(training, "_get_verda_client", lambda: client)
    monkeypatch.setattr(training, "_gpu_availability_cache", {})
    monkeypatch.setattr(training, "_gpu_availability_cache_time", {})

    response = training.get_gpu_availability()
    by_instance_type = {item.instance_type: item for item in response.available}
    assert "1H100.80S.22V" in by_instance_type
    assert "2H100.80S.60V" in by_instance_type
