from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.auth import StrictModel


class MediaOut(StrictModel):
    id: str
    purpose: str
    mime_type: str
    byte_size: int
    sha256: str
    width: int
    height: int
    state: str
    expires_at: datetime | None
    content_url: str


class ImageDetectionIn(StrictModel):
    media_id: str = Field(min_length=36, max_length=36)


class DetectionBoxOut(StrictModel):
    person_link: dict | None = None
    id: str | None = None
    box_index: int
    class_id: int
    class_name: str
    confidence: float
    bbox: list[float]


class DetectionOut(StrictModel):
    rendered_media_id: str | None = None
    batch_id: str | None = None
    batch_index: int | None = None
    warning_codes: list[str] = []
    id: str
    owner_id: str
    source: Literal["IMAGE", "CAMERA"]
    state: str
    review_status: str
    model_id: str | None
    model_sha256: str | None
    config_snapshot: dict
    source_media_id: str | None
    image_width: int | None
    image_height: int | None
    boxes: list[DetectionBoxOut]
    error_code: str | None
    version: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CameraSessionIn(StrictModel):
    capture_interval_ms: int = Field(default=500, ge=200, le=2000)
    client_label: str | None = Field(default=None, max_length=100)


class CameraSessionOut(StrictModel):
    generation: int = 1
    id: str
    owner_id: str
    state: str
    capture_interval_ms: int = 500
    max_frame_bytes: int = 1_048_576
    heartbeat_interval_seconds: int = 15
    expires_at: datetime
    created_at: datetime


class FrameBoxOut(StrictModel):
    box_index: int
    class_id: int
    class_name: str
    confidence: float
    bbox: list[float]


class FrameResultOut(StrictModel):
    generation: int = 1
    frame_id: str
    frame_seq: int
    image_width: int
    image_height: int
    model_id: str
    threshold: float
    boxes: list[FrameBoxOut]
    inference_ms: int
    result_expires_at: datetime
    persist_status: Literal["NOT_REQUIRED", "SAVED", "COOLDOWN", "FAILED"]
    detection_id: str | None = None
    warning_codes: list[str]
