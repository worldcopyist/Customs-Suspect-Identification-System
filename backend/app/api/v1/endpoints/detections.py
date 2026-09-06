"""Durable still-image detection tasks and result lookup."""

from fastapi import APIRouter, Depends, Request, Response, Header
from datetime import datetime
from typing import Literal
from app.services.business import allow, paginate, detection_access
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import request_id
from app.db.session import get_db
from app.models import Detection, Media, User
from app.schemas.common import SuccessResponse
from app.schemas.detection import DetectionBoxOut, DetectionOut, ImageDetectionIn
from app.services.security import ApiError, now, require_csrf, require_user
from app.workers.inference import default_config


router = APIRouter(prefix="/detections", tags=["detections"])


def _allowed(user: User, permission: str) -> bool:
    return user.role in {"ADMIN", "SUPER_ADMIN"} or permission in user.permissions


def detection_out(item: Detection) -> DetectionOut:
    return DetectionOut(id=item.id, owner_id=item.owner_id, source=item.source, state=item.state,
                        rendered_media_id=item.rendered_media_id, batch_id=item.batch_id, batch_index=item.batch_index, warning_codes=item.warning_codes or [],
                        review_status=item.review_status, model_id=item.model_id, model_sha256=item.model_sha256,
                        config_snapshot=item.config_snapshot, source_media_id=item.source_media_id,
                        image_width=item.image_width, image_height=item.image_height,
                        boxes=[DetectionBoxOut(id=box.id, box_index=box.box_index, class_id=box.class_id,
                                               class_name=box.class_name, confidence=box.confidence, bbox=box.bbox, person_link=box.person_link)
                               for box in item.boxes], error_code=item.error_code, version=item.version,
                        created_at=item.created_at, started_at=item.started_at, finished_at=item.finished_at)


@router.get("", response_model=SuccessResponse[dict])
def list_detections(request: Request, page: int = 1, page_size: int = 20, source:Literal["IMAGE","CAMERA"]|None=None, state:Literal["PENDING","QUEUED","RUNNING","SUCCEEDED","FAILED","CANCELLED"]|None=None, review_status:Literal["NOT_APPLICABLE","PENDING","RETAINED","FALSE_POSITIVE"]|None=None, created_from:datetime|None=None, created_to:datetime|None=None, db: Session = Depends(get_db),
                    user: User = Depends(require_user)) -> SuccessResponse[dict]:
    """Return durable records only; the UI must not synthesize example detections."""
    if not _allowed(user, "detection.read"):
        raise ApiError(403, "PERMISSION_DENIED", "没有检测记录查看权限")
    if not 1 <= page or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    statement = select(Detection).options(selectinload(Detection.boxes)).order_by(Detection.created_at.desc(), Detection.id.desc())
    if user.role == "USER":
        statement = statement.where(Detection.owner_id == user.id)
    statement=statement.where(Detection.deleted_at.is_(None))
    for key,value in (("source",source),("state",state),("review_status",review_status)):
        if value:statement=statement.where(getattr(Detection,key)==value)
    if created_from:statement=statement.where(Detection.created_at>=created_from)
    if created_to:statement=statement.where(Detection.created_at<created_to)
    return SuccessResponse(data=paginate(db,statement,page,page_size,lambda x:detection_out(x).model_dump(mode="json")),request_id=request_id(request))


@router.post("/images", status_code=202, response_model=SuccessResponse[DetectionOut])
def detect_image(payload: ImageDetectionIn, request: Request, response:Response, idempotency_key:str|None=Header(None), db: Session = Depends(get_db),
                 user: User = Depends(require_user)) -> SuccessResponse[DetectionOut]:
    require_csrf(request, db)
    if not _allowed(user, "detection.image"):
        raise ApiError(403, "PERMISSION_DENIED", "没有图片检测权限")
    replay=idempotency_replay(db,user,request,idempotency_key,payload.model_dump())
    if replay:
        response.headers["Idempotency-Replayed"]="true"
        return SuccessResponse(data=DetectionOut(**replay.response_data),request_id=request_id(request))
    from sqlalchemy import func
    if (db.scalar(select(func.count()).select_from(Detection).where(Detection.owner_id==user.id,Detection.state.in_(["QUEUED","RUNNING"]))) or 0)>=2:
        raise ApiError(429,"USER_INFERENCE_LIMIT","本人已有两个待处理任务")
    coordinator = request.app.state.inference_coordinator
    if not coordinator.available:
        raise ApiError(503, "MODEL_UNAVAILABLE", "本地检测模型不可用")
    media = db.get(Media, payload.media_id)
    if media is None or media.owner_id != user.id or media.purpose != "DETECTION_IMAGE":
        raise ApiError(404, "NOT_FOUND", "检测图片不存在")
    if media.state != "STAGED":
        raise ApiError(409, "MEDIA_ALREADY_BOUND", "图片已被其他检测任务绑定")
    if media.expires_at is not None and media.expires_at.replace(tzinfo=now().tzinfo) <= now():
        raise ApiError(410, "MEDIA_EXPIRED", "图片已过期")
    if not coordinator.reserve():
        raise ApiError(429, "INFERENCE_QUEUE_FULL", "检测队列已满")
    config = default_config()
    item = Detection(owner_id=user.id, source="IMAGE", state="QUEUED", review_status="NOT_APPLICABLE",
                     model_id="suspect-yolo11n-best", model_sha256=coordinator.settings.yolo_model_sha256,
                     source_media_id=media.id, config_snapshot={"threshold": config.threshold, "iou": config.iou,
                     "imgsz": config.imgsz, "max_det": config.max_det, "device": config.device,
                     "preprocess_version": config.preprocess_version,"queued_at":now().isoformat()})
    media.state = "BOUND"
    try:
        db.add(item)
        db.flush()
        remember_idempotency(db,user,request,idempotency_key,payload.model_dump(),202,detection_out(item).model_dump(mode="json"))
        db.commit()
        coordinator.submit_reserved_image(item.id)
    except Exception:
        coordinator.release_reservation()
        raise
    return SuccessResponse(data=detection_out(item), request_id=request_id(request))


@router.get("/{detection_id}", response_model=SuccessResponse[DetectionOut])
def get_detection(detection_id: str, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_user)) -> SuccessResponse[DetectionOut]:
    if not _allowed(user, "detection.read"):
        raise ApiError(403, "PERMISSION_DENIED", "没有检测记录查看权限")
    item = db.scalar(select(Detection).options(selectinload(Detection.boxes)).where(Detection.id == detection_id))
    if item is None or item.deleted_at or (user.role == "USER" and item.owner_id != user.id):
        raise ApiError(404, "NOT_FOUND", "检测记录不存在")
    return SuccessResponse(data=detection_out(item), request_id=request_id(request))


@router.post("/{detection_id}/cancel", response_model=SuccessResponse[DetectionOut])
def cancel_detection(detection_id: str, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_user)) -> SuccessResponse[DetectionOut]:
    require_csrf(request, db)
    item = detection_access(db,user,detection_id)
    allow(user,"detection.image" if item.source=="IMAGE" else "detection.camera")
    if item is None or (user.role == "USER" and item.owner_id != user.id):
        raise ApiError(404, "NOT_FOUND", "检测记录不存在")
    if item.state not in {"PENDING","QUEUED"}:
        raise ApiError(409, "TASK_NOT_CANCELLABLE", "任务已开始或已结束，不能取消")
    from sqlalchemy import update
    changed=db.execute(update(Detection).where(Detection.id==item.id,Detection.state.in_(["PENDING","QUEUED"])).values(state="CANCELLED",finished_at=now())).rowcount
    if not changed:raise ApiError(409,"TASK_NOT_CANCELLABLE","任务已开始或已结束，不能取消")
    db.commit()
    return SuccessResponse(data=detection_out(item), request_id=request_id(request))
