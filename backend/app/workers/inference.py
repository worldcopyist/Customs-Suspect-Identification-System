"""Isolated, single-model YOLO inference worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from importlib.util import find_spec
import math
import multiprocessing as mp
from pathlib import Path
from queue import Empty
import threading
from time import monotonic
from typing import Any
from uuid import uuid4

from PIL import Image

from app.core.config import Settings, get_settings


EXPECTED_NAMES = {0: "handsome"}


class InferenceError(RuntimeError):
    def __init__(self, code: str, message: str = "本地模型推理失败") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InferenceConfig:
    threshold: float
    iou: float
    imgsz: int
    max_det: int
    device: str
    preprocess_version: str = "rgb-exif-v1"


@dataclass(frozen=True)
class InferenceBox:
    box_index: int
    class_id: int
    class_name: str
    confidence: float
    bbox: list[float]


@dataclass(frozen=True)
class InferenceOutput:
    task_id: str
    model_sha256: str
    image_width: int
    image_height: int
    boxes: list[InferenceBox]
    inference_ms: int
    warning_codes: list[str]
    device: str
    preprocess_version: str


def default_config(settings: Settings | None = None) -> InferenceConfig:
    active = settings or get_settings()
    return InferenceConfig(active.yolo_confidence, active.yolo_iou, active.yolo_imgsz, active.yolo_max_det, active.yolo_device)


def _model_path(settings: Settings) -> Path:
    """Resolve an approved relative model name without allowing path escape."""
    root = settings.models_root.resolve()
    name = Path(settings.yolo_model_filename)
    if name.is_absolute() or name.suffix.lower() != ".pt" or len(name.parts) != 1:
        raise InferenceError("MODEL_CONFIGURATION_INVALID")
    raw_candidate = root / name
    candidate = raw_candidate.resolve()
    if candidate.parent != root or raw_candidate.is_symlink() or not candidate.is_file():
        raise InferenceError("MODEL_UNAVAILABLE")
    if sha256(candidate.read_bytes()).hexdigest() != settings.yolo_model_sha256:
        raise InferenceError("MODEL_HASH_MISMATCH")
    return candidate


def model_ready(settings: Settings | None = None) -> bool:
    if find_spec("ultralytics") is None:
        return False
    try:
        _model_path(settings or get_settings())
    except InferenceError:
        return False
    return True


def _as_rgb(image_bytes: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
            image.load()
            return image
    except Exception as exc:  # Pillow exception subclasses vary by version.
        raise InferenceError("INVALID_IMAGE") from exc


def _parse_results(results: Any, config: InferenceConfig, width: int, height: int) -> tuple[list[InferenceBox], list[str]]:
    if not isinstance(results, (list, tuple)) or len(results) != 1:
        raise InferenceError("MODEL_OUTPUT_INVALID")
    result = results[0]
    names = {int(key): str(value) for key, value in dict(result.names).items()}
    if names != EXPECTED_NAMES or tuple(int(item) for item in result.orig_shape) != (height, width):
        raise InferenceError("MODEL_CONTRACT_CHANGED")
    raw = result.boxes
    if raw is None:
        return [], []
    xyxy, confidence, classes = raw.xyxy.cpu().tolist(), raw.conf.cpu().tolist(), raw.cls.cpu().tolist()
    if not (len(xyxy) == len(confidence) == len(classes)):
        raise InferenceError("MODEL_OUTPUT_INVALID")
    parsed: list[tuple[float, list[float]]] = []
    clipped = False
    for coords, score_value, class_value in zip(xyxy, confidence, classes, strict=True):
        if len(coords) != 4 or not all(math.isfinite(float(value)) for value in [*coords, score_value, class_value]):
            raise InferenceError("MODEL_OUTPUT_INVALID")
        class_id, score = int(class_value), float(score_value)
        if class_value != class_id or class_id != 0:
            raise InferenceError("MODEL_CONTRACT_CHANGED")
        if not 0 <= score <= 1:
            raise InferenceError("MODEL_OUTPUT_INVALID")
        original = [float(value) for value in coords]
        bbox = [min(max(original[0], 0.0), width), min(max(original[1], 0.0), height), min(max(original[2], 0.0), width), min(max(original[3], 0.0), height)]
        if any(abs(before - after) > 1.0 for before, after in zip(original, bbox, strict=True)) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise InferenceError("MODEL_OUTPUT_INVALID")
        clipped = clipped or bbox != original
        if score >= config.threshold:
            parsed.append((score, bbox))
    parsed.sort(key=lambda item: (-item[0], *item[1]))
    warnings = (["BOX_COORDINATES_CLIPPED"] if clipped else []) + (["MAX_DETECTIONS_REACHED"] if len(parsed) >= config.max_det else [])
    return [InferenceBox(index, 0, EXPECTED_NAMES[0], score, bbox) for index, (score, bbox) in enumerate(parsed)], warnings


def _child_main(requests: Any, responses: Any, model_path: str, model_sha: str) -> None:
    """Child entry point: it deliberately has no database or browser credentials."""
    model: Any | None = None
    load_error: str | None = None
    try:
        from ultralytics import YOLO
        model = YOLO(model_path)
        if {int(key): str(value) for key, value in dict(model.names).items()} != EXPECTED_NAMES or getattr(model, "task", None) != "detect":
            model, load_error = None, "MODEL_CONTRACT_CHANGED"
    except Exception:
        load_error = "MODEL_LOAD_FAILED"
    while True:
        task = requests.get()
        if task is None:
            return
        task_id = task["task_id"]
        try:
            if model is None:
                raise InferenceError(load_error or "MODEL_LOAD_FAILED")
            config = InferenceConfig(**task["config"])
            image = _as_rgb(task["image_bytes"])
            started = monotonic()
            results = model.predict(source=image, conf=config.threshold, iou=config.iou, imgsz=config.imgsz, max_det=config.max_det,
                                    device=config.device, save=False, save_txt=False, show=False, augment=False, verbose=False)
            boxes, warnings = _parse_results(results, config, image.width, image.height)
            responses.put({"task_id": task_id, "ok": True, "model_sha256": model_sha, "image_width": image.width,
                           "image_height": image.height, "boxes": [asdict(box) for box in boxes],
                           "inference_ms": round((monotonic() - started) * 1000), "warning_codes": warnings,
                           "device": config.device, "preprocess_version": config.preprocess_version})
        except InferenceError as exc:
            responses.put({"task_id": task_id, "ok": False, "code": exc.code})
        except Exception:
            responses.put({"task_id": task_id, "ok": False, "code": "MODEL_RUNTIME_FAILED"})


class YoloInferenceWorker:
    """A single child process and a lock guarantee one active model prediction."""
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._process: mp.Process | None = None
        self._requests: Any | None = None
        self._responses: Any | None = None

    def _stop(self) -> None:
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=2)
        self._process = None
        for item in (self._requests, self._responses):
            if item is not None:
                item.close()
        self._requests = self._responses = None

    def _start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._stop()
        path = _model_path(self.settings)
        context = mp.get_context("spawn")
        self._requests, self._responses = context.Queue(maxsize=1), context.Queue(maxsize=1)
        self._process = context.Process(target=_child_main, args=(self._requests, self._responses, str(path), self.settings.yolo_model_sha256), daemon=True, name="suspect-yolo-inference")
        self._process.start()

    def close(self) -> None:
        with self._lock:
            self._stop()

    def predict(self, image_bytes: bytes, config: InferenceConfig | None = None) -> InferenceOutput:
        active = config or default_config(self.settings)
        if not (0.001 <= active.threshold <= 0.99 and 0 <= active.iou <= 1 and active.imgsz in {320, 640} and 1 <= active.max_det <= 100):
            raise InferenceError("INFERENCE_CONFIGURATION_INVALID")
        _as_rgb(image_bytes)  # reject malformed input before it reaches the child
        with self._lock:
            self._start()
            assert self._requests is not None and self._responses is not None
            task_id = str(uuid4())
            self._requests.put({"task_id": task_id, "image_bytes": image_bytes, "config": asdict(active)})
            try:
                reply = self._responses.get(timeout=self.settings.inference_timeout_seconds)
            except Empty as exc:
                self._stop()
                raise InferenceError("INFERENCE_TIMEOUT") from exc
            if reply.get("task_id") != task_id:
                self._stop()
                raise InferenceError("MODEL_PROTOCOL_INVALID")
            if not reply.get("ok"):
                raise InferenceError(str(reply.get("code", "MODEL_RUNTIME_FAILED")))
            return InferenceOutput(task_id, str(reply["model_sha256"]), int(reply["image_width"]), int(reply["image_height"]),
                                   [InferenceBox(**box) for box in reply["boxes"]], int(reply["inference_ms"]),
                                   [str(value) for value in reply["warning_codes"]], str(reply["device"]), str(reply["preprocess_version"]))
