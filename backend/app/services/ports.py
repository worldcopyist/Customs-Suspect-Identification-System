"""基础设施端口：业务模块依赖这些协议，而非直接耦合模型或厂商 SDK。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class InferenceJob:
    task_id: str
    image_path: Path
    model_sha256: str
    threshold: float
    iou: float
    imgsz: int
    max_det: int


class InferenceGateway(Protocol):
    async def submit(self, job: InferenceJob) -> object: ...


class LlmGateway(Protocol):
    async def generate_text(self, frozen_request: object) -> object: ...


class MediaStore(Protocol):
    async def stage(self, payload: bytes, mime_type: str) -> object: ...
