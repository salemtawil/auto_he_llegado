from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import PhotoStatus
from core.validators import (
    validate_image_path,
    validate_non_empty_string,
    validate_optional_string,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)


class PhotoCreate(DomainModel):
    id: str | None = None
    original_filename: str = Field(alias="original_name")
    storage_path: str = Field(alias="file_path")
    status: PhotoStatus = PhotoStatus.PENDING
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @field_validator("original_filename")
    @classmethod
    def _validate_original_filename(cls, value: str) -> str:
        return validate_non_empty_string(value, "original_filename")

    @field_validator("storage_path")
    @classmethod
    def _validate_storage_path(cls, value: str) -> str:
        return validate_image_path(value, "storage_path")

    @field_validator("source", "error_message")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return validate_optional_string(value, "optional_text")


class PhotoRecord(PhotoCreate):
    id: str
    reserved_at: datetime | None = None
    consumed_at: datetime | None = None
    reserved_by_process_id: str | None = None
    created_at: datetime | None = None


class PhotoUpdate(DomainModel):
    status: PhotoStatus | None = None
    storage_path: str | None = Field(default=None, alias="file_path")
    reserved_at: datetime | None = None
    consumed_at: datetime | None = None
    reserved_by_process_id: str | None = None
    error_message: str | None = None

    @field_validator("storage_path")
    @classmethod
    def _validate_optional_storage_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_image_path(value, "storage_path")

    @field_validator("reserved_by_process_id", "error_message")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return validate_optional_string(value, "optional_text")


class ProcessLogCreate(DomainModel):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    site: str
    action: str
    phone: str
    agent_name: str
    device_name: str
    station_name: str
    block_price: str
    block_time: str
    final_status: str
    phase: str
    page_message: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None

    @field_validator(
        "site",
        "action",
        "phone",
        "agent_name",
        "device_name",
        "station_name",
        "block_price",
        "block_time",
        "final_status",
        "phase",
    )
    @classmethod
    def _validate_required_text(cls, value: str, info) -> str:
        return validate_non_empty_string(value, info.field_name or "field")

    @field_validator("page_message", "error_message")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return validate_optional_string(value, "optional_text")


class ProcessLogRecord(ProcessLogCreate):
    id: int


class ProcessLogUpdate(DomainModel):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    site: str | None = None
    action: str | None = None
    phone: str | None = None
    agent_name: str | None = None
    device_name: str | None = None
    station_name: str | None = None
    block_price: str | None = None
    block_time: str | None = None
    final_status: str | None = None
    phase: str | None = None
    page_message: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None

    @field_validator(
        "site",
        "action",
        "phone",
        "agent_name",
        "device_name",
        "station_name",
        "block_price",
        "block_time",
        "final_status",
        "phase",
        "page_message",
        "error_message",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return validate_optional_string(value, "optional_text")


class UploadItemResult(DomainModel):
    source_path: str
    original_filename: str
    photo_id: str | None = None
    storage_path: str | None = None
    success: bool
    message: str
    processing_status: str = "Pendiente"
    storage_uploaded: bool = False
    storage_error: str | None = None
    database_inserted: bool = False
    database_error: str | None = None
    local_cleanup_message: str | None = None
    local_cleanup_error: str | None = None
    local_file_deleted: bool = False
    failed_file_path: str | None = None


class UploadBatchProgress(DomainModel):
    total_files: int = 0
    processed_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    current_index: int = 0
    status_text: str = "Listo para cargar."
    current_file: str | None = None
    current_file_status: str | None = None
    result: UploadItemResult | None = None


class LocalConfig(DomainModel):
    agent_name: str = "Agente Local"
    agent_name_confirmed: bool = False
    flow_engine: str = "traditional"
    keep_browser_open: bool = True
    enable_browser_extension: bool = True
    browser_extension_overlay: bool = True
    page_timeout_seconds: int = 180
    action_timeout_seconds: int = 180
    paripe_block_wait_seconds: int = 300
    max_selfie_retries: int = 10
    last_result_filter: str = "general"
    theme_mode: str = "light"


class ProcessExecutionRequest(DomainModel):
    process_id: str | None = None
    page_name: str
    action_name: str
    phone_number: str
    password: str
    agent_name: str
    execution_mode: str = "traditional"


class ProcessExecutionResult(DomainModel):
    process_id: str | None = None
    process_log_id: int | None = None
    page_name: str
    action_name: str
    phone_number: str
    agent_name: str = "N/A"
    execution_mode: str = "normal"
    success: bool
    message: str
    final_status: str = "failed"
    phase: str = "unknown"
    station_name: str = "N/A"
    block_price: str = "N/A"
    block_time: str = "N/A"
    block_duration: str = "N/A"
    selfie_retry_count: int = 0
    deepfakescore_retries: int = 0
    deepfakescore_activated: bool = False
    completed_at: datetime | None = None


class ReservedPhoto(DomainModel):
    photo_id: str
    storage_path: str
    local_path: str
    original_filename: str
    reserved_by_process_id: str | None = None


class SiteExecutionResult(DomainModel):
    success: bool
    message: str
    final_status: str
    phase: str
    station_name: str = "N/A"
    block_price: str = "N/A"
    block_time: str = "N/A"
    block_duration: str = "N/A"
    selfie_retry_count: int = 0
    deepfakescore_retries: int = 0
    deepfakescore_activated: bool = False
    reserved_photo_id: str | None = None


class LastResultSnapshot(DomainModel):
    completed_at: datetime | None = None
    phone_number: str
    agent_name: str = "N/A"
    station_name: str = "N/A"
    block_price: str = "N/A"
    block_duration: str = "N/A"
    action_name: str
    deepfakescore_retries: int = 0
    final_status: str = "failed"
    site_name: str
    success: bool
    message: str
