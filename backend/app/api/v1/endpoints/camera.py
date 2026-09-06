"""Camera-frame detection: bounded frames, one in-flight frame, short cache."""

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, Request, Response, Header
from sqlalchemy import func, select, update
from pydantic import Field
from app.schemas.auth import StrictModel
from app.services.business import result as envelope
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.errors import request_id
from app.db.session import get_db
from app.models import CameraSession, Detection, DetectionBox, Media, User
from app.schemas.common import SuccessResponse
from app.schemas.detection import CameraSessionIn, CameraSessionOut, FrameBoxOut, FrameResultOut
from app.services.detection import InputImageError, normalize_image
from app.services.security import ApiError, now, require_csrf, require_user
from app.workers.inference import InferenceError, default_config


router = APIRouter(prefix="/camera", tags=["camera"])


def _allowed(user: User) -> bool:
    return user.role in {"ADMIN", "SUPER_ADMIN"} or "detection.camera" in user.permissions


def _session_out(item: CameraSession) -> CameraSessionOut:
    return CameraSessionOut(id=item.id, owner_id=item.owner_id, state=item.state, generation=item.generation,capture_interval_ms=item.capture_interval_ms,expires_at=item.expires_at, created_at=item.created_at)


def _owned_active(db: Session, session_id: str, user: User) -> CameraSession:
    if not _allowed(user):raise ApiError(403,"PERMISSION_DENIED","没有摄像头检测权限")
    item = db.get(CameraSession, session_id)
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "摄像头会话不存在")
    if item.state not in {"ACTIVE","PAUSED"} or item.expires_at.replace(tzinfo=now().tzinfo) <= now():
        if item.state in {"ACTIVE","PAUSED"}:item.state = "EXPIRED"
        db.commit()
        raise ApiError(410, "CAMERA_SESSION_CLOSED", "摄像头会话已关闭")
    return item


def _persist_detected_frame(db: Session, owner_id: str, image: bytes, width: int, height: int, output) -> str:
    """Persist the exact analyzed JPEG before writing a CAMERA detection."""
    settings = get_settings()
    storage_key = f"{uuid4()}.jpg"
    target = (settings.media_root.resolve() / storage_key).resolve()
    if target.parent != settings.media_root.resolve():
        raise OSError("unsafe media path")
    target.write_bytes(image)
    config = default_config()
    try:
        media = Media(id=str(uuid4()), owner_id=owner_id, purpose="CAMERA_FRAME", mime_type="image/jpeg", byte_size=len(image),
                      sha256=sha256(image).hexdigest(), width=width, height=height, state="BOUND", storage_key=storage_key)
        detection = Detection(id=str(uuid4()), owner_id=owner_id, source="CAMERA", state="SUCCEEDED", review_status="PENDING" if output.boxes else "NOT_APPLICABLE",
                              model_id="suspect-yolo11n-best", model_sha256=output.model_sha256, source_media_id=media.id,
                              image_width=width, image_height=height, started_at=now(), finished_at=now(),
                              config_snapshot={"threshold": config.threshold, "iou": config.iou, "imgsz": config.imgsz,
                              "max_det": config.max_det, "device": output.device, "preprocess_version": output.preprocess_version,
                              "inference_ms": output.inference_ms, "warning_codes": output.warning_codes})
        detection.boxes = [DetectionBox(box_index=box.box_index, class_id=box.class_id, class_name=box.class_name,
                                        confidence=box.confidence, bbox=box.bbox) for box in output.boxes]
        db.add_all([media, detection])
        db.commit()
        from app.services.detection import render_detection
        render_detection(db,detection)
        return detection.id
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise


@router.post("/sessions", status_code=201, response_model=SuccessResponse[CameraSessionOut])
def create_session(payload: CameraSessionIn, request: Request, response:Response, idempotency_key:str|None=Header(None), db: Session = Depends(get_db),
                   user: User = Depends(require_user)) -> SuccessResponse[CameraSessionOut]:
    require_csrf(request, db)
    if not _allowed(user):
        raise ApiError(403, "PERMISSION_DENIED", "没有摄像头检测权限")
    replay=idempotency_replay(db,user,request,idempotency_key,payload.model_dump())
    if replay:
        response.headers["Idempotency-Replayed"]="true"
        return SuccessResponse(data=CameraSessionOut(**replay.response_data),request_id=request_id(request))
    db.execute(update(CameraSession).where(CameraSession.state.in_(["ACTIVE","PAUSED"]),CameraSession.expires_at<=now()).values(state="EXPIRED"))
    active = db.scalar(select(CameraSession).where(CameraSession.owner_id == user.id, CameraSession.state.in_(["ACTIVE","PAUSED"])))
    if active is not None and active.expires_at.replace(tzinfo=now().tzinfo) > now():
        raise ApiError(409, "CAMERA_SESSION_EXISTS", "当前用户已有活动摄像头会话")
    total = db.scalar(select(func.count()).select_from(CameraSession).where(CameraSession.state.in_(["ACTIVE","PAUSED"]))) or 0
    if total >= get_settings().camera_session_limit:
        raise ApiError(429, "CAMERA_LIMIT_REACHED", "活动摄像头会话已达上限")
    item = CameraSession(owner_id=user.id, state="ACTIVE", client_label=payload.client_label,
                         generation=1,capture_interval_ms=payload.capture_interval_ms,
                         last_activity_at=now(), expires_at=now() + timedelta(seconds=45))
    db.add(item)
    db.flush();remember_idempotency(db,user,request,idempotency_key,payload.model_dump(),201,_session_out(item).model_dump(mode="json"))
    db.commit()
    return SuccessResponse(data=_session_out(item), request_id=request_id(request))


@router.post("/sessions/{session_id}/heartbeat", response_model=SuccessResponse[dict])
def heartbeat(session_id: str, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    item = _owned_active(db, session_id, user)
    item.last_activity_at, item.expires_at = now(), now() + timedelta(seconds=45)
    db.commit()
    return SuccessResponse(data={"state": item.state, "expires_at": item.expires_at}, request_id=request_id(request))


@router.post("/sessions/{session_id}/frames", response_model=SuccessResponse[FrameResultOut])
async def detect_frame(session_id: str, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_user)) -> SuccessResponse[FrameResultOut]:
    require_csrf(request, db)
    if not _allowed(user):
        raise ApiError(403, "PERMISSION_DENIED", "没有摄像头检测权限")
    form = await request.form()
    file, raw_seq = form.get("file"), form.get("frame_seq")
    if not isinstance(file, UploadFile):
        raise ApiError(422, "VALIDATION_ERROR", "缺少摄像头帧")
    try:
        frame_seq = int(str(raw_seq))
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "frame_seq 必须是整数") from exc
    if frame_seq < 1:
        raise ApiError(422, "VALIDATION_ERROR", "frame_seq 必须从 1 开始递增")
    item = _owned_active(db, session_id, user)
    try:generation=int(str(form.get("generation")))
    except ValueError:raise ApiError(422,"VALIDATION_ERROR","缺少有效 generation")
    if generation!=item.generation:raise ApiError(409,"STALE_CAMERA_GENERATION","摄像头代际已变化，请刷新会话")
    if item.state=="PAUSED":raise ApiError(409,"CAMERA_PAUSED","检测已暂停")
    raw = await file.read(1048577)
    try:
        image, width, height = normalize_image(raw, frame=True)
    except InputImageError as exc:
        status = 413 if exc.code == "FILE_TOO_LARGE" else 415 if exc.code == "UNSUPPORTED_MEDIA" else 422
        raise ApiError(status, exc.code, "摄像头帧不符合要求") from exc
    cache = request.app.state.camera_cache
    lock = request.app.state.camera_cache_lock
    digest = sha256(image).hexdigest()
    with lock:
        previous = cache.get(session_id, {}).get(frame_seq)
        highest = request.app.state.camera_last_seq.get(session_id, 0)
        if previous is not None:
            if previous["expires_at"]<=now():raise ApiError(409,"FRAME_SEQUENCE_CONFLICT","帧已过期，请递增帧序号")
            if previous["sha256"] != digest:
                raise ApiError(409, "FRAME_SEQUENCE_CONFLICT", "相同序号不能提交不同帧")
            return SuccessResponse(data=previous["result"], request_id=request_id(request))
        if frame_seq <= highest:
            raise ApiError(409, "FRAME_SEQUENCE_CONFLICT", "帧序号必须单调递增")
        if session_id in request.app.state.camera_in_flight:
            raise ApiError(429, "FRAME_IN_FLIGHT", "上一帧仍在处理中")
        request.app.state.camera_in_flight.add(session_id)
        request.app.state.camera_last_seq[session_id]=frame_seq
    coordinator=request.app.state.inference_coordinator
    if not coordinator.reserve():
        with lock:request.app.state.camera_in_flight.discard(session_id)
        raise ApiError(429,"INFERENCE_QUEUE_FULL","推理队列已满")
    db.commit()
    try:
        output = await anyio.to_thread.run_sync(request.app.state.inference_coordinator.worker.predict, image)
    except InferenceError as exc:
        raise ApiError(504 if exc.code == "INFERENCE_TIMEOUT" else 503, exc.code, "本地模型推理失败") from exc
    finally:
        coordinator.release_reservation()
        with lock:
            request.app.state.camera_in_flight.discard(session_id)
    db.expire_all()
    item=_owned_active(db,session_id,user)
    accepted=db.execute(update(CameraSession).where(CameraSession.id==session_id,CameraSession.generation==generation,CameraSession.state=="ACTIVE").values(last_activity_at=now(),expires_at=now()+timedelta(seconds=45))).rowcount
    if not accepted:raise ApiError(409,"STALE_CAMERA_GENERATION","暂停或关闭前的结果已丢弃")
    expires_at = now() + timedelta(seconds=get_settings().camera_frame_cache_seconds)
    persist_status, detection_id, extra_warnings = "NOT_REQUIRED", None, []
    if output.boxes:
        with lock:
            last_saved = request.app.state.camera_last_saved.get(session_id)
        if last_saved is not None and now() - last_saved < timedelta(seconds=10):
            persist_status = "COOLDOWN"
        else:
            try:
                detection_id = _persist_detected_frame(db, user.id, image, width, height, output)
                persist_status = "SAVED"
                with lock:
                    request.app.state.camera_last_saved[session_id] = now()
            except (OSError, SQLAlchemyError):
                persist_status, extra_warnings = "FAILED", ["MEDIA_PERSIST_FAILED"]
    result = FrameResultOut(frame_id=str(uuid4()), frame_seq=frame_seq, image_width=width, image_height=height,
                            generation=generation,
                            model_id="suspect-yolo11n-best", threshold=default_config().threshold,
                            boxes=[FrameBoxOut(box_index=box.box_index, class_id=box.class_id, class_name=box.class_name,
                                               confidence=box.confidence, bbox=box.bbox) for box in output.boxes],
                            inference_ms=output.inference_ms, result_expires_at=expires_at,
                            persist_status=persist_status, detection_id=detection_id, warning_codes=output.warning_codes + extra_warnings)
    with lock:
        frames = cache.setdefault(session_id, {})
        frames[frame_seq] = {"sha256": digest, "result": result, "image": image, "output":output,"expires_at": expires_at}
        request.app.state.camera_last_seq[session_id] = frame_seq
        for sequence, saved in list(frames.items()):
            if saved["expires_at"] <= now() or len(frames) > 3:
                del frames[sequence]
    db.commit()
    return SuccessResponse(data=result, request_id=request_id(request))


@router.post("/sessions/{session_id}/stop", response_model=SuccessResponse[CameraSessionOut])
def stop_session(session_id: str, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_user)) -> SuccessResponse[CameraSessionOut]:
    require_csrf(request, db)
    item = db.get(CameraSession, session_id)
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "摄像头会话不存在")
    item.state = "STOPPED"
    item.generation+=1
    db.commit()
    with request.app.state.camera_cache_lock:
        request.app.state.camera_cache.pop(session_id, None)
        request.app.state.camera_last_seq.pop(session_id, None)
        request.app.state.camera_last_saved.pop(session_id, None)
    return SuccessResponse(data=_session_out(item), request_id=request_id(request))

class GenerationIn(StrictModel):
    generation:int=Field(ge=1)
class ResumeIn(GenerationIn):
    capture_interval_ms:int|None=Field(default=None,ge=200,le=2000)
class SnapshotIn(GenerationIn):
    frame_id:str=Field(min_length=36,max_length=36)

@router.get("/sessions/{session_id}")
def detail(session_id:str,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    if not _allowed(user):raise ApiError(403,"PERMISSION_DENIED","没有摄像头检测权限")
    item=db.get(CameraSession,session_id)
    if not item or item.owner_id!=user.id:raise ApiError(404,"NOT_FOUND","会话不存在")
    return envelope(request,_session_out(item))

def transition(id,payload,request,db,user,state):
    require_csrf(request,db);item=_owned_active(db,id,user)
    if item.generation!=payload.generation:raise ApiError(409,"STALE_CAMERA_GENERATION","会话状态已变化")
    if item.state!=state:
        changed=db.execute(update(CameraSession).where(CameraSession.id==id,CameraSession.generation==payload.generation).values(state=state,generation=payload.generation+1)).rowcount
        if not changed:raise ApiError(409,"STALE_CAMERA_GENERATION","会话状态已变化")
    if isinstance(payload,ResumeIn) and payload.capture_interval_ms:item.capture_interval_ms=payload.capture_interval_ms
    db.commit();db.refresh(item)
    with request.app.state.camera_cache_lock:request.app.state.camera_cache.pop(id,None)
    return envelope(request,_session_out(item))
@router.post("/sessions/{session_id}/pause")
def pause(session_id:str,payload:GenerationIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    return transition(session_id,payload,request,db,user,"PAUSED")
@router.post("/sessions/{session_id}/resume")
def resume(session_id:str,payload:ResumeIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    return transition(session_id,payload,request,db,user,"ACTIVE")
@router.post("/sessions/{session_id}/snapshots",status_code=201)
def snapshot(session_id:str,payload:SnapshotIn,request:Request,response:Response,idempotency_key:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);item=_owned_active(db,session_id,user)
    if item.state!="ACTIVE":raise ApiError(409,"CAMERA_PAUSED","暂停后不能保存旧帧")
    if item.generation!=payload.generation:raise ApiError(409,"STALE_CAMERA_GENERATION","会话状态已变化")
    replay=idempotency_replay(db,user,request,idempotency_key,payload.model_dump())
    if replay:return envelope(request,replay.response_data)
    from app.api.v1.endpoints.detections import detection_out
    with request.app.state.camera_cache_lock:
        saved=next((x for x in request.app.state.camera_cache.get(session_id,{}).values() if x["result"].frame_id==payload.frame_id),None)
        if not saved or saved["expires_at"]<=now():raise ApiError(410,"FRAME_EXPIRED","当前帧已过期，请重新采集")
        if saved["result"].detection_id:response.status_code=200
        else:saved["result"].detection_id=_persist_detected_frame(db,user.id,saved["image"],saved["result"].image_width,saved["result"].image_height,saved["output"])
        row=db.get(Detection,saved["result"].detection_id);out=detection_out(row).model_dump(mode="json")
    remember_idempotency(db,user,request,idempotency_key,payload.model_dump(),response.status_code,out);db.commit()
    return envelope(request,out)
