"""Writes to the Bronze landing zone in ADLS Gen2 through the managed identity."""

import json
from typing import Protocol


class Landing(Protocol):
    def exists(self, path: str) -> bool: ...
    def write_json(
        self, path: str, document: object, metadata: dict[str, str] | None = None
    ) -> None: ...
    def write_bytes(
        self, path: str, data: bytes, metadata: dict[str, str] | None = None
    ) -> None: ...
    def list_names(self, prefix: str) -> set[str]: ...


class BlobLanding:
    """Landing zone backed by one container of an Azure Storage account.

    Paths are blob names inside the container (for example
    calendly/landing/2026/10/27/invitee.created_<uuid>.json). Writes overwrite by name, so
    repeating a write with the same path is idempotent.
    """

    def __init__(self, account_url: str, container: str, credential=None):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self._credential = credential or DefaultAzureCredential()
        self._service = BlobServiceClient(account_url=account_url, credential=self._credential)
        self._container = self._service.get_container_client(container)

    def exists(self, path: str) -> bool:
        return self._container.get_blob_client(path).exists()

    def write_bytes(self, path: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        from azure.storage.blob import ContentSettings

        self._container.upload_blob(
            name=path,
            data=data,
            overwrite=True,
            metadata=metadata or {},
            content_settings=ContentSettings(content_type="application/json"),
        )

    def write_json(
        self, path: str, document: object, metadata: dict[str, str] | None = None
    ) -> None:
        self.write_bytes(path, json.dumps(document, ensure_ascii=False).encode("utf-8"), metadata)

    def list_names(self, prefix: str) -> set[str]:
        return {
            blob.name.rsplit("/", 1)[-1]
            for blob in self._container.list_blobs(name_starts_with=prefix.rstrip("/") + "/")
        }


class MemoryLanding:
    """In-memory landing zone for unit tests."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    def exists(self, path: str) -> bool:
        return path in self.blobs

    def write_bytes(self, path: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        self.blobs[path] = data
        self.metadata[path] = metadata or {}

    def write_json(
        self, path: str, document: object, metadata: dict[str, str] | None = None
    ) -> None:
        self.write_bytes(path, json.dumps(document, ensure_ascii=False).encode("utf-8"), metadata)

    def list_names(self, prefix: str) -> set[str]:
        prefix = prefix.rstrip("/") + "/"
        return {p.rsplit("/", 1)[-1] for p in self.blobs if p.startswith(prefix)}
