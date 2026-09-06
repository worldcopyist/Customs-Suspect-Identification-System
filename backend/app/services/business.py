"""Shared authorization, versioning and safe audit helpers."""
import json
from datetime import UTC, timedelta
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update, func
from app.models import AuditLog, Detection
from app.services.security import ApiError

def allow(user, permission):
    if user.role == "USER" and permission not in user.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "没有此功能权限")

def result(request, data):
    return {"data": jsonable_encoder(data), "request_id": request.state.request_id}

def fields(row, names):
    return {name:getattr(row, name) for name in names.split()}

def paginate(db, stmt, page=1, page_size=20, serializer=lambda x:x):
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "INVALID_FILTER", "分页参数无效")
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return {"items":[serializer(x) for x in db.scalars(stmt.offset((page-1)*page_size).limit(page_size))], "total":total,"page":page,"page_size":page_size}

def version(db, row, expected):
    count = db.execute(update(type(row)).where(type(row).id == row.id, type(row).version == expected).values(version=expected+1).execution_options(synchronize_session=False)).rowcount
    if not count: raise ApiError(409, "VERSION_CONFLICT", "数据已更新，请刷新后重试")
    db.refresh(row)

def match_version(header):
    import re
    if header is None: raise ApiError(428,"VERSION_REQUIRED","需要 If-Match 版本")
    if not re.fullmatch(r'"v[1-9][0-9]*"', header): raise ApiError(422,"INVALID_FILTER","版本格式错误")
    return int(header[2:-1])

def audit(db, request, user, action, object_type, object_id, before=None, after=None, outcome="SUCCESS"):
    db.add(AuditLog(actor_id=user.id if user else None, action=action, details=json.dumps(jsonable_encoder({"object_type":object_type,"object_id":object_id,"before":before or {},"after":after or {},"outcome":outcome,"request_id":getattr(request.state,"request_id",None)}),ensure_ascii=False)))

def detection_access(db, user, record_id, review=False):
    allow(user, "detection.read")
    if review: allow(user,"detection.review")
    row=db.get(Detection, record_id)
    if not row or row.deleted_at or (user.role=="USER" and row.owner_id!=user.id): raise ApiError(404,"NOT_FOUND","检测记录不存在")
    if review and (row.state!="SUCCEEDED" or not row.boxes): raise ApiError(409,"DETECTION_NOT_REVIEWABLE","只有成功且含检测框的记录可复核或关联")
    return row

def interval(start, end, max_days=31):
    if not start or not end or start.tzinfo is None or end.tzinfo is None or not start < end or end-start > timedelta(days=max_days):
        raise ApiError(422,"INVALID_FILTER","请提供带时区的起止时间，跨度不得超过31天")
    return start.astimezone(UTC),end.astimezone(UTC)
