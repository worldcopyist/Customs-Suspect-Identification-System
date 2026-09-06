"""Controlled image intake used by the image-detection workflow."""

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, Header
from sqlalchemy import select
from app.models import Detection
from app.models.extension import Person
from app.services.business import allow
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.errors import request_id
from app.db.session import get_db
from app.models import Media, User
from app.schemas.common import SuccessResponse
from app.schemas.detection import MediaOut
from app.services.detection import InputImageError, media_path, normalize_image
from app.services.security import ApiError, now, require_csrf, require_user


router = APIRouter(prefix="/media", tags=["media"])


def _allowed(user: User, permission: str) -> bool:
    return user.role in {"ADMIN", "SUPER_ADMIN"} or permission in user.permissions


def media_out(media: Media) -> MediaOut:
    return MediaOut(id=media.id, purpose=media.purpose, mime_type=media.mime_type, byte_size=media.byte_size,
                    sha256=media.sha256, width=media.width, height=media.height, state=media.state,
                    expires_at=media.expires_at, content_url=f"/api/v1/media/{media.id}/content")


@router.post("", status_code=201, response_model=SuccessResponse[MediaOut])
async def upload_media(request: Request, response:Response, idempotency_key:str|None=Header(None), db: Session = Depends(get_db),
                       user: User = Depends(require_user)) -> SuccessResponse[MediaOut]:
    require_csrf(request, db)
    form = await request.form()
    file, purpose = form.get("file"), form.get("purpose", "DETECTION_IMAGE")
    if not isinstance(file, UploadFile):
        raise ApiError(422, "VALIDATION_ERROR", "缺少图片文件")
    if purpose not in {"DETECTION_IMAGE","PERSON_PHOTO"} or (purpose=="PERSON_PHOTO" and user.role=="USER") or (purpose=="DETECTION_IMAGE" and not _allowed(user,"detection.image")):
        raise ApiError(403, "PERMISSION_DENIED", "没有图片检测权限")
    raw = await file.read(10*1024*1024+1)
    payload={"purpose":purpose,"sha256":sha256(raw).hexdigest()}
    replay=idempotency_replay(db,user,request,idempotency_key,payload)
    if replay:
        response.headers["Idempotency-Replayed"]="true"
        return SuccessResponse(data=MediaOut(**replay.response_data),request_id=request_id(request))
    try:
        normalized, width, height = normalize_image(raw)
    except InputImageError as exc:
        status = 413 if exc.code == "FILE_TOO_LARGE" else 415 if exc.code == "UNSUPPORTED_MEDIA" else 422
        raise ApiError(status, exc.code, "上传图片不符合检测要求") from exc
    settings = get_settings()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid4()}.jpg"
    target = (settings.media_root.resolve() / storage_key).resolve()
    if target.parent != settings.media_root.resolve():
        raise ApiError(500, "MEDIA_STORAGE_ERROR", "媒体存储异常")
    try:
        target.write_bytes(normalized)
        media = Media(owner_id=user.id, purpose=purpose, mime_type="image/jpeg", byte_size=len(normalized),
                      sha256=sha256(normalized).hexdigest(), width=width, height=height, state="STAGED",
                      storage_key=storage_key, upload_byte_size=len(raw), expires_at=now() + timedelta(hours=24))
        db.add(media)
        db.flush()
        remember_idempotency(db,user,request,idempotency_key,payload,201,media_out(media).model_dump(mode="json"))
        db.commit()
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ApiError(503, "MEDIA_PERSIST_FAILED", "媒体文件保存失败") from exc
    return SuccessResponse(data=media_out(media), request_id=request_id(request))


def authorized_media(db,user,media_id):
    media = db.get(Media, media_id)
    if media is None or media.state not in {"STAGED", "BOUND"}:
        raise ApiError(404, "NOT_FOUND", "媒体不存在")
    if media.state=="STAGED":
        if media.owner_id!=user.id:raise ApiError(404,"NOT_FOUND","媒体不存在")
    elif media.purpose=="PERSON_PHOTO":
        allow(user,"person.read")
        if not db.scalar(select(Person).where(Person.photo_media_id==media.id,Person.status!="DELETED")):raise ApiError(404,"NOT_FOUND","媒体不存在")
    else:
        allow(user,"detection.read")
        record=db.scalar(select(Detection).where((Detection.source_media_id==media.id)|(Detection.rendered_media_id==media.id),Detection.deleted_at.is_(None)))
        if not record or (user.role=="USER" and record.owner_id!=user.id):raise ApiError(404,"NOT_FOUND","媒体不存在")
    if media.expires_at is not None and media.expires_at.replace(tzinfo=now().tzinfo) <= now() and media.state == "STAGED":
        raise ApiError(410, "MEDIA_EXPIRED", "媒体已过期")
    return media

@router.get("/{media_id}")
def metadata(media_id:str,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    return SuccessResponse(data=media_out(authorized_media(db,user,media_id)),request_id=request_id(request))

@router.delete("/{media_id}",status_code=204)
def remove(media_id:str,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db)
    media=db.get(Media,media_id)
    if not media or media.owner_id!=user.id:raise ApiError(404,"NOT_FOUND","媒体不存在")
    if media.state=="BOUND":raise ApiError(409,"MEDIA_ALREADY_BOUND","媒体已绑定")
    media.state="TRASH";db.commit()
    return Response(status_code=204)

@router.get("/{media_id}/content")
def media_content(media_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)) -> FileResponse:
    media=authorized_media(db,user,media_id)
    path = media_path(media)
    if not path.is_file():
        raise ApiError(410, "MEDIA_MISSING", "媒体文件已丢失")
    return FileResponse(path, media_type=media.mime_type, headers={"Cache-Control": "private, no-store"})
