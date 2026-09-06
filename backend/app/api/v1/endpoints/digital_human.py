"""Administrator-managed digital-human model asset."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.errors import request_id
from app.db.session import get_db
from app.models import Media, User
from app.schemas.common import SuccessResponse
from app.services.security import ApiError, require_csrf, require_manager, require_user

router = APIRouter(prefix="/digital-human", tags=["digital-human"])
ALLOWED = {".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

def out(item: Media | None) -> dict:
    if item is None: return {"asset": None}
    return {"asset": {"id": item.id, "file_name": item.storage_key.split("_", 1)[-1], "mime_type": item.mime_type, "byte_size": item.byte_size, "content_url": f"/api/v1/media/{item.id}/content"}}

@router.get("/model", response_model=SuccessResponse[dict])
def get_model(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    item = db.scalar(select(Media).where(Media.purpose == "DIGITAL_HUMAN_MODEL").order_by(Media.created_at.desc()))
    return SuccessResponse(data=out(item), request_id=request_id(request))

@router.post("/model", response_model=SuccessResponse[dict])
async def upload_model(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db); require_manager(user)
    file = (await request.form()).get("file")
    if not isinstance(file, UploadFile): raise ApiError(422, "VALIDATION_ERROR", "缺少模型文件")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED: raise ApiError(415, "UNSUPPORTED_MODEL", "仅支持 GLB、GLTF、PNG、JPG 或 JPEG")
    raw = await file.read()
    if not raw or len(raw) > 25 * 1024 * 1024: raise ApiError(413, "MODEL_TOO_LARGE", "模型文件需在 25MB 以内")
    settings = get_settings(); settings.media_root.mkdir(parents=True, exist_ok=True)
    storage_key = f"digital_{uuid4()}_{Path(file.filename or 'model').name}"
    target = (settings.media_root.resolve() / storage_key).resolve()
    if target.parent != settings.media_root.resolve(): raise ApiError(500, "MEDIA_STORAGE_ERROR", "存储路径异常")
    target.write_bytes(raw)
    item = Media(owner_id=user.id, purpose="DIGITAL_HUMAN_MODEL", mime_type=ALLOWED[suffix], byte_size=len(raw), sha256=sha256(raw).hexdigest(), width=0, height=0, state="BOUND", storage_key=storage_key, expires_at=None)
    db.add(item); db.commit()
    return SuccessResponse(data=out(item), request_id=request_id(request))
