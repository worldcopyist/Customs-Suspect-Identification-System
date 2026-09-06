"""Server-side normalization, persistence and scheduling for local detection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import threading
from uuid import uuid4

from PIL import Image, ImageOps, ImageDraw, ImageFont, UnidentifiedImageError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import Detection, DetectionBox, Media, User
from app.models.extension import DetectionBatch
from app.services.security import now
from app.workers.inference import InferenceError, YoloInferenceWorker, default_config, model_ready


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 10_000
MAX_FRAME_BYTES = 1 * 1024 * 1024
MAX_FRAME_WIDTH = 1920
MAX_FRAME_HEIGHT = 1080


class InputImageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_image(raw: bytes, *, frame: bool = False) -> tuple[bytes, int, int]:
    """Verify, orient and flatten an untrusted image into deterministic JPEG bytes."""
    byte_limit = MAX_FRAME_BYTES if frame else MAX_IMAGE_BYTES
    if not raw:
        raise InputImageError("INVALID_IMAGE")
    if len(raw) > byte_limit:
        raise InputImageError("FILE_TOO_LARGE")
    try:
        with Image.open(BytesIO(raw)) as checked:
            if checked.width*checked.height>MAX_IMAGE_PIXELS or max(checked.size)>MAX_IMAGE_EDGE:
                raise InputImageError("INVALID_IMAGE")
            if checked.format not in {"JPEG", "PNG"}:
                raise InputImageError("UNSUPPORTED_MEDIA")
            checked.verify()
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS or max(width, height) > MAX_IMAGE_EDGE:
                raise InputImageError("INVALID_IMAGE")
            if frame and (width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT):
                raise InputImageError("INVALID_IMAGE")
            if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                canvas = Image.new("RGBA", image.size, "white")
                canvas.alpha_composite(image.convert("RGBA"))
                image = canvas.convert("RGB")
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=95, optimize=True)
            return output.getvalue(), width, height
    except InputImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InputImageError("INVALID_IMAGE") from exc


def media_path(media: Media, settings: Settings | None = None) -> Path:
    root = (settings or get_settings()).media_root.resolve()
    path = (root / media.storage_key).resolve()
    if path.parent != root:
        raise InputImageError("MEDIA_MISSING")
    return path


class InferenceCoordinator:
    """Serially schedules durable image jobs; camera frames share the same worker lock."""
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.worker = YoloInferenceWorker(self.settings)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="detection-dispatch")
        # One running task plus at most the configured waiting capacity.
        self._slots = threading.BoundedSemaphore(self.settings.inference_queue_limit + 1)
        self._closing = threading.Event()
        self._scheduler = threading.Thread(target=self._schedule_batches, daemon=True, name="batch-scheduler")
        self._scheduler.start()

    def _schedule_batches(self):
        from sqlalchemy import func
        from app.api.v1.endpoints.records import batch_counts
        import logging
        while not self._closing.wait(0.5):
            try:
                with SessionLocal() as db:
                    # Previously accepted but never executed singles are recovered
                    # with the original deadline, not silently treated as failures.
                    for row in db.scalars(select(Detection).where(Detection.state=="PENDING",Detection.batch_id.is_(None),Detection.source=="IMAGE",Detection.deleted_at.is_(None)).order_by(Detection.created_at)):
                        user=db.get(User,row.owner_id)
                        if not user or user.status!="ACTIVE" or (user.role=="USER" and "detection.image" not in user.permissions):
                            row.state="CANCELLED";row.finished_at=now();continue
                        active=db.scalar(select(func.count()).select_from(Detection).where(Detection.owner_id==row.owner_id,Detection.state.in_(["QUEUED","RUNNING"]))) or 0
                        if active>=2:continue
                        if not self.reserve():break
                        row.state="QUEUED";row.started_at=None
                        db.commit();self.submit_reserved_image(row.id)
                        break
                    db.commit()
                    for batch in db.scalars(select(DetectionBatch).where(DetectionBatch.state=="RUNNING").order_by(DetectionBatch.created_at)):
                        items=batch_counts(db,batch)
                        user=db.get(User,batch.owner_id)
                        permitted=user and user.status=="ACTIVE" and (user.role!="USER" or "detection.image" in user.permissions)
                        for row in items:
                            if row.state!="PENDING":continue
                            if batch.cancel_requested or not permitted:
                                row.state="CANCELLED";row.finished_at=now();continue
                            active=db.scalar(select(func.count()).select_from(Detection).where(Detection.owner_id==row.owner_id,Detection.state.in_(["QUEUED","RUNNING"]))) or 0
                            if active>=2 or not self.reserve():break
                            row.state="QUEUED";row.started_at=None
                            # Queue admission starts the per-item deadline.
                            row.config_snapshot={**row.config_snapshot,"queued_at":row.config_snapshot.get("queued_at") or now().isoformat()}
                            db.commit();self.submit_reserved_image(row.id)
                            break
                        db.flush();batch_counts(db,batch);db.commit()
            except Exception as exc:
                logging.getLogger("customs_training").error("batch_scheduler_failed exception_type=%s",type(exc).__name__)

    @property
    def available(self) -> bool:
        return model_ready(self.settings)

    def reserve(self) -> bool:
        return self._slots.acquire(blocking=False)

    def submit_reserved_image(self, detection_id: str) -> None:
        self._executor.submit(self._run_image, detection_id)

    def release_reservation(self) -> None:
        self._slots.release()

    def _run_image(self, detection_id: str) -> None:
        try:
            with SessionLocal() as db:
                detection = db.get(Detection, detection_id)
                if detection is None or detection.state != "QUEUED":
                    return
                from sqlalchemy import update
                claimed=db.execute(update(Detection).where(Detection.id==detection_id,Detection.state=="QUEUED").values(state="RUNNING",started_at=now())).rowcount
                if not claimed:return
                db.commit()
                db.refresh(detection)
                try:
                    owner=db.get(User,detection.owner_id)
                    if not owner or owner.status!="ACTIVE" or (owner.role=="USER" and "detection.image" not in owner.permissions):raise InferenceError("PERMISSION_DENIED")
                    if detection.model_sha256!=self.settings.yolo_model_sha256:raise InferenceError("MODEL_CHANGED")
                    frozen=default_config(self.settings)
                    for key,value in (("threshold",frozen.threshold),("iou",frozen.iou),("imgsz",frozen.imgsz),("max_det",frozen.max_det)):
                        if detection.config_snapshot.get(key)!=value:raise InferenceError("MODEL_CHANGED")
                    from datetime import datetime
                    queued_at=detection.config_snapshot.get("queued_at")
                    if queued_at and now()-datetime.fromisoformat(queued_at)>timedelta(seconds=self.settings.inference_timeout_seconds):raise InferenceError("INFERENCE_TIMEOUT")
                    media = db.get(Media, detection.source_media_id)
                    if media is None or media.state != "BOUND":
                        raise InferenceError("MEDIA_MISSING")
                    output = self.worker.predict(media_path(media, self.settings).read_bytes())
                    detection.image_width, detection.image_height = output.image_width, output.image_height
                    detection.model_sha256 = output.model_sha256
                    detection.model_id = "suspect-yolo11n-best"
                    detection.config_snapshot = {
                        "threshold": default_config(self.settings).threshold, "iou": default_config(self.settings).iou,
                        "imgsz": default_config(self.settings).imgsz, "max_det": default_config(self.settings).max_det,
                        "device": output.device, "preprocess_version": output.preprocess_version,
                        "inference_ms": output.inference_ms, "warning_codes": output.warning_codes,
                    }
                    detection.boxes = [DetectionBox(box_index=item.box_index, class_id=item.class_id, class_name=item.class_name,
                                                    confidence=item.confidence, bbox=item.bbox) for item in output.boxes]
                    detection.state = "SUCCEEDED"
                    detection.review_status = "PENDING" if output.boxes else "NOT_APPLICABLE"
                    detection.error_code = None
                except InferenceError as exc:
                    detection.state, detection.review_status = "FAILED", "NOT_APPLICABLE"
                    detection.error_code = exc.code
                except OSError:
                    detection.state, detection.review_status = "FAILED", "NOT_APPLICABLE"
                    detection.error_code = "MEDIA_MISSING"
                except Exception:
                    detection.state,detection.error_code="FAILED","INFERENCE_FAILED"
                detection.finished_at = now()
                db.commit()
                if detection.state=="SUCCEEDED":
                    render_detection(db,detection,self.settings)
                else:
                    from app.models.extension import OperationLog
                    db.add(OperationLog(level="ERROR",module="detection",event_code=detection.error_code or "INFERENCE_FAILED",safe_context={"detection_id":detection.id}));db.commit()
        finally:
            self._slots.release()

    def close(self) -> None:
        self._closing.set()
        self._scheduler.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.worker.close()

def render_detection(db, detection, settings=None):
    """Make a separately hashed derived JPEG. Never mutate the inference input."""
    settings=settings or get_settings()
    try:
        media=db.get(Media,detection.source_media_id)
        owner=db.get(User,detection.owner_id)
        with Image.open(media_path(media,settings)) as original:
            picture=original.convert("RGB")
        draw=ImageDraw.Draw(picture)
        font=ImageFont.load_default(size=max(12,min(22,picture.width//40)))
        for box in detection.boxes:
            draw.rectangle(box.bbox,outline="red",width=3)
            draw.text((box.bbox[0],max(0,box.bbox[1]-20)),f"sus {box.confidence:.3f}",fill="red",font=font)
        # Local font is optional; English fallback always preserves the training label.
        label="TRAINING DATA / 实训数据"
        for path in ("/System/Library/Fonts/PingFang.ttc","C:/Windows/Fonts/msyh.ttc","/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
            if Path(path).is_file():font=ImageFont.truetype(path,max(12,min(20,picture.width//40)));break
        lines=[label,f"{owner.username} | {detection.finished_at.isoformat()}",detection.id]
        draw.rectangle((0,0,picture.width,78),fill="#071b34")
        for i,line in enumerate(lines):draw.text((6,3+i*24),line,fill="white",font=font)
        output=BytesIO();picture.save(output,"JPEG",quality=92);raw=output.getvalue();key=f"{uuid4()}.jpg"
        (settings.media_root/key).write_bytes(raw)
        rendered=Media(owner_id=detection.owner_id,purpose="DETECTION_RENDERED",mime_type="image/jpeg",byte_size=len(raw),upload_byte_size=0,sha256=sha256(raw).hexdigest(),width=picture.width,height=picture.height,state="BOUND",storage_key=key)
        db.add(rendered);db.flush();detection.rendered_media_id=rendered.id;db.commit()
    except Exception:
        db.rollback()
        detection.warning_codes=list(set((detection.warning_codes or [])+["RENDERED_MEDIA_FAILED"]))
        db.commit()
