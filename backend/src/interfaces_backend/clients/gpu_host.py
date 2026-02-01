from __future__ import annotations

from percus_ai.gpu_host.models import (
    LoadRequest,
    LoadResponse,
    StartRequest,
    StartResponse,
    StatusResponse,
    StopRequest,
    StopResponse,
)
from percus_ai.gpu_host.server import (
    load_model as _load_model,
    start_worker as _start_worker,
    status as _status,
    stop_worker as _stop_worker,
)


class GpuHostClient:
    def start(self, request: StartRequest) -> StartResponse:
        return _start_worker(request)

    def stop(self, request: StopRequest) -> StopResponse:
        return _stop_worker(request)

    def load(self, request: LoadRequest) -> LoadResponse:
        return _load_model(request)

    def status(self) -> StatusResponse:
        return _status()
