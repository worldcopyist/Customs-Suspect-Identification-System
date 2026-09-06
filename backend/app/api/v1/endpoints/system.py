"""Read-only health, auditable maintenance views and precisely scoped metrics."""
import json
from datetime import datetime, timedelta, UTC
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Detection, DetectionBox, User, AuditLog, ProviderConfig
from app.models.extension import AgentProfile, OperationLog
from app.core.config import get_settings
from app.services.security import require_user, require_manager, now, ApiError
from app.services.business import allow, result, fields, paginate, interval
from app.api.v1.endpoints.community import online_query

router=APIRouter(tags=["system"])
@router.get("/health/live")
def live(request:Request):return result(request,{"status":"alive"})
def avatar_data():
    path=get_settings().avatar_asset
    ready=bool(path and path.is_file() and path.suffix.lower()==".glb" and 20<=path.stat().st_size<=30*1048576)
    return {"status":"READY" if ready else "UNAVAILABLE","asset_id":"deployment-avatar" if ready else None,"content_url":"/api/v1/system/avatar/assets/deployment-avatar" if ready else None,"fallback_label":"尚未部署正式3D资产；占位展示不影响文字交流"}
@router.get("/system/avatar")
def avatar(request:Request,user=Depends(require_user)):
    allow(user,"assistant.use");return result(request,avatar_data())
@router.get("/system/avatar/assets/{asset_id}")
def asset(asset_id:str,user=Depends(require_user)):
    allow(user,"assistant.use")
    if asset_id!="deployment-avatar" or avatar_data()["status"]!="READY":raise ApiError(404,"NOT_FOUND","3D资源不可用")
    return FileResponse(get_settings().avatar_asset,media_type="model/gltf-binary",headers={"Cache-Control":"private,no-store"})
@router.get("/system/status")
def status(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    from app.services.llm import validation_fingerprint
    ready=any(p.enabled and p.capabilities and p.validation_fingerprint==validation_fingerprint(p) for p in db.scalars(select(ProviderConfig)))
    return result(request,{"database":"READY","model":"READY" if request.app.state.inference_coordinator.available else "UNAVAILABLE","llm":"READY" if ready else "UNAVAILABLE","avatar":avatar_data()["status"]})

def hit_stmt(stamp,owner=None):
    stmt=select(Detection).where(Detection.deleted_at.is_(None),Detection.state=="SUCCEEDED",Detection.finished_at<stamp,Detection.boxes.any())
    if owner:stmt=stmt.where(Detection.owner_id==owner)
    return stmt
def metrics(db,stamp,owner=None):
    hits=hit_stmt(stamp,owner)
    count=lambda stmt:db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return {"as_of":stamp,"recent_window_seconds":60,"recent_hit_record_count":count(hits.where(Detection.finished_at>=stamp-timedelta(seconds=60))),"total_hit_record_count":count(hits),"detected_box_count":count(select(DetectionBox).where(DetectionBox.detection_id.in_(hits.with_only_columns(Detection.id)))),"false_positive_record_count":count(hits.where(Detection.review_status=="FALSE_POSITIVE"))}
@router.get("/dashboard/summary")
def own_summary(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"detection.read");stamp=now();out=metrics(db,stamp,user.id)
    out["pending_review_count"]=db.scalar(select(func.count()).select_from(Detection).where(Detection.owner_id==user.id,Detection.deleted_at.is_(None),Detection.state=="SUCCEEDED",Detection.review_status=="PENDING")) or 0
    return result(request,out)
@router.get("/admin/dashboard/summary")
def summary(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);stamp=now();out=metrics(db,stamp)
    out.update(user_total_count=db.scalar(select(func.count()).select_from(User).where(User.status!="DELETED")) or 0,online_user_count=db.scalar(select(func.count()).select_from(online_query(stamp).subquery())) or 0,agent_profile_count=db.scalar(select(func.count()).select_from(AgentProfile).where(AgentProfile.status!="ARCHIVED")) or 0)
    return result(request,out)
@router.get("/admin/dashboard/trends")
def trends(request:Request,from_:datetime=Query(alias="from"),to:datetime=Query(),bucket:Literal["HOUR","DAY"]="HOUR",db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);stamp=now();start,end=interval(from_,to)
    if end>stamp:raise ApiError(422,"INVALID_FILTER","结束时间不得晚于当前时间")
    cursor=start.replace(minute=0,second=0,microsecond=0)
    step=timedelta(hours=1)
    if bucket=="DAY":cursor=cursor.replace(hour=0);step=timedelta(days=1)
    items=[]
    while cursor<end:
        stmt=hit_stmt(stamp).where(Detection.finished_at>=max(cursor,start),Detection.finished_at<min(cursor+step,end))
        n=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        boxes=db.scalar(select(func.count()).select_from(DetectionBox).where(DetectionBox.detection_id.in_(stmt.with_only_columns(Detection.id)))) or 0
        false=db.scalar(select(func.count()).select_from(stmt.where(Detection.review_status=="FALSE_POSITIVE").subquery())) or 0
        items.append({"bucket_start":cursor,"bucket_end":cursor+step,"hit_record_count":n,"detected_box_count":boxes,"false_positive_record_count":false});cursor+=step
    return result(request,{"from":start,"to":end,"bucket":bucket,"as_of":stamp,"items":items})

@router.get("/admin/operations/logs")
def logs(request:Request,page:int=1,page_size:int=20,level:Literal["INFO","WARN","ERROR"]|None=None,module:str|None=None,event_code:str|None=Query(None,max_length=80),trace_id:UUID|None=Query(None,alias="request_id"),created_from:datetime|None=None,created_to:datetime|None=None,db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);stmt=select(OperationLog)
    if level:stmt=stmt.where(OperationLog.level==level)
    if module:stmt=stmt.where(OperationLog.module==module)
    if event_code:stmt=stmt.where(OperationLog.event_code==event_code)
    if trace_id:stmt=stmt.where(OperationLog.request_id==str(trace_id))
    if created_from and created_to:interval(created_from,created_to)
    if created_from:stmt=stmt.where(OperationLog.created_at>=created_from)
    if created_to:stmt=stmt.where(OperationLog.created_at<created_to)
    return result(request,paginate(db,stmt.order_by(OperationLog.created_at.desc(),OperationLog.id.desc()),page,page_size,lambda x:fields(x,"id level module event_code request_id safe_context created_at")))
@router.get("/admin/audit-logs")
def audits(request:Request,page:int=1,page_size:int=20,actor_id:UUID|None=None,action:str|None=None,object_type:str|None=None,object_id:UUID|None=None,trace_id:UUID|None=Query(None,alias="request_id"),created_from:datetime|None=None,created_to:datetime|None=None,db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);stmt=select(AuditLog)
    if actor_id:stmt=stmt.where(AuditLog.actor_id==str(actor_id))
    if action:stmt=stmt.where(AuditLog.action==action)
    if trace_id:stmt=stmt.where(func.json_extract(AuditLog.details,"$.request_id")==str(trace_id))
    if created_from and created_to:interval(created_from,created_to)
    if object_type:stmt=stmt.where(func.json_extract(AuditLog.details,"$.object_type")==object_type)
    if object_id:stmt=stmt.where(func.json_extract(AuditLog.details,"$.object_id")==str(object_id))
    if created_from:stmt=stmt.where(AuditLog.created_at>=created_from)
    if created_to:stmt=stmt.where(AuditLog.created_at<created_to)
    def out(row):
        data=json.loads(row.details)
        # Legacy audit metadata is restricted to known structural fields.
        return {**fields(row,"id actor_id action created_at"),"object_type":data.get("object_type","USER" if row.target_user_id else "CONVERSATION"),"object_id":data.get("object_id",row.target_user_id or data.get("conversation_id")),"before":data.get("before",{}),"after":data.get("after",{}),"outcome":data.get("outcome","SUCCESS"),"request_id":data.get("request_id")}
    return result(request,paginate(db,stmt.order_by(AuditLog.created_at.desc(),AuditLog.id.desc()),page,page_size,out))
