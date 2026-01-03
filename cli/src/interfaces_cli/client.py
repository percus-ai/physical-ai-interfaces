"""HTTP client for Backend API."""

import os
import httpx


def get_backend_url() -> str:
    return os.environ.get("PERCUS_BACKEND_URL", "http://localhost:8000")


class PercusClient:
    def __init__(self, base_url: str = None):
        self.base_url = base_url or get_backend_url()
        self._client = httpx.Client(base_url=self.base_url)

    def health(self) -> dict:
        response = self._client.get("/health")
        response.raise_for_status()
        return response.json()

    def list_projects(self) -> list:
        response = self._client.get("/api/projects")
        response.raise_for_status()
        return response.json()

    def list_datasets(self) -> list:
        response = self._client.get("/api/datasets")
        response.raise_for_status()
        return response.json()

    def get_config(self) -> dict:
        response = self._client.get("/api/config")
        response.raise_for_status()
        return response.json()
