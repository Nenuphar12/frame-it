"""LocalSend protocol v2 payloads (camelCase on the wire)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = "2.1"


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def wire(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True)


class DeviceInfo(_Wire):
    alias: str = Field(default="", max_length=256)
    version: str = Field(default="2.0", max_length=16)
    device_model: str | None = Field(default=None, max_length=128)
    device_type: str | None = Field(default=None, max_length=32)
    fingerprint: str = Field(default="", max_length=256)
    port: int = 53317
    protocol: str = "https"
    download: bool = False


class Announcement(DeviceInfo):
    announce: bool = False
    announcement: bool = False  # protocol v1 name of `announce`


class FileMetadata(_Wire):
    modified: str | None = None
    accessed: str | None = None


class FileOffer(_Wire):
    id: str = Field(max_length=256)
    file_name: str = Field(max_length=1024)
    size: int = Field(ge=0)
    file_type: str = Field(default="", max_length=256)
    sha256: str | None = Field(default=None, max_length=128)
    preview: str | None = None
    metadata: FileMetadata | None = None


class PrepareUploadRequest(_Wire):
    info: DeviceInfo
    files: dict[str, FileOffer] = Field(max_length=10_000)


class PrepareUploadResponse(_Wire):
    session_id: str
    files: dict[str, str]
