"""Batch acceptance and human decisions never rewrite original detector boxes."""
from datetime import datetime
from uuid import UUID, uuid4
from typing import Literal
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select,update
from sqlalchemy.orm import Session
from pydantic import Field, model_validator
from app.db.session import get_db
from app.models import Detection, Media
from app.models.extension import DetectionBatch, DetectionHistory, Person
from app.schemas.auth import StrictModel
from app.services.security import require_user, require_csrf, require_manager, ApiError, now
from app.services.business import allow, audit, fields, match_version, paginate, result, version, detection_access
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from app.api.v1.endpoints.detections import detection_out
from app.workers.inference import default_config

router=APIRouter(prefix="/detections",tags=["records"])
class BatchIn(StrictModel):
    media_ids:list[UUID]=Field(min_length=1,max_length=10)
    @model_validator(mode="after")
    def unique(self):
        if len(set(self.media_ids))!=len(self.media_ids):raise ValueError("不得重复引用图片")
        return self
class ReviewIn(StrictModel):
    review_status:Literal["RETAINED","FALSE_POSITIVE"]
    comment:str=Field(min_length=1,max_length=1000)
    expected_version:int=Field(ge=1)
class LinkIn(StrictModel):
    person_id:UUID
    comment:str=Field(min_length=1,max_length=1000)
    expected_version:int=Field(ge=1)

def batch_counts(db,batch):
    items=list(db.scalars(select(Detection).where(Detection.batch_id==batch.id).order_by(Detection.batch_index)))
    if batch.state=="RUNNING":
        counts={"total_count":len(items),"succeeded_count":sum(x.state=="SUCCEEDED" for x in items),"failed_count":sum(x.state=="FAILED" for x in items),"cancelled_count":sum(x.state=="CANCELLED" for x in items),"hit_image_count":sum(x.state=="SUCCEEDED" and bool(x.boxes) for x in items)}
        counts["processed_count"]=counts["succeeded_count"]+counts["failed_count"]+counts["cancelled_count"]
        batch.counts=counts
        if counts["processed_count"]==len(items):
            batch.state="CANCELLED" if batch.cancel_requested else "COMPLETED"
            batch.finished_at=now()
    return items
def batch_out(db,batch,detail=False):
    items=batch_counts(db,batch)
    out={**fields(batch,"id owner_id state cancel_requested created_at finished_at"),**batch.counts}
    if detail:out["items"]=[{"id":x.id,"batch_index":x.batch_index,"hidden":True,"reason":"DELETED"} if x.deleted_at else detection_out(x).model_dump(mode="json") for x in items]
    return out
def batch_access(db,user,id):
    allow(user,"detection.read")
    batch=db.get(DetectionBatch,str(id))
    if not batch or (user.role=="USER" and batch.owner_id!=user.id):raise ApiError(404,"NOT_FOUND","批次不存在")
    return batch
@router.post("/batches",status_code=202)
def create_batch(payload:BatchIn,request:Request,response:Response,idempotency_key:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"detection.image")
    data=payload.model_dump(mode="json")
    replay=idempotency_replay(db,user,request,idempotency_key,data)
    if replay:
        response.headers["Idempotency-Replayed"]="true"
        return result(request,replay.response_data)
    coordinator=request.app.state.inference_coordinator
    if not coordinator.available:raise ApiError(503,"MODEL_UNAVAILABLE","本地模型不可用")
    if db.scalar(select(DetectionBatch).where(DetectionBatch.owner_id==user.id,DetectionBatch.state=="RUNNING")):raise ApiError(409,"BATCH_ALREADY_ACTIVE","请等待或取消当前批次")
    media=[]
    for i,id in enumerate(payload.media_ids):
        m=db.get(Media,str(id))
        if not m or m.owner_id!=user.id or m.purpose!="DETECTION_IMAGE" or m.state!="STAGED" or (m.expires_at and m.expires_at.replace(tzinfo=now().tzinfo)<=now()):raise ApiError(422,"INVALID_BATCH","该图片不可用于本次检测",{"index":i})
        media.append(m)
    if sum(x.upload_byte_size for x in media)>100*1024*1024:raise ApiError(413,"BATCH_BYTES_EXCEEDED","批次超出100MiB")
    batch=DetectionBatch(id=str(uuid4()),owner_id=user.id);db.add(batch)
    cfg=default_config()
    for i,m in enumerate(media):
        m.state="BOUND"
        db.add(Detection(owner_id=user.id,source="IMAGE",state="PENDING",batch_id=batch.id,batch_index=i,source_media_id=m.id,model_id="suspect-yolo11n-best",model_sha256=coordinator.settings.yolo_model_sha256,config_snapshot={"threshold":cfg.threshold,"iou":cfg.iou,"imgsz":cfg.imgsz,"max_det":cfg.max_det,"device":cfg.device,"preprocess_version":cfg.preprocess_version}))
    db.flush();out=batch_out(db,batch,True)
    from fastapi.encoders import jsonable_encoder
    remember_idempotency(db,user,request,idempotency_key,data,202,jsonable_encoder(out));db.commit()
    return result(request,out)
@router.get("/batches")
def batches(request:Request,page:int=1,page_size:int=20,state:Literal["RUNNING","COMPLETED","CANCELLED"]|None=None,created_from:datetime|None=None,created_to:datetime|None=None,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"detection.read")
    stmt=select(DetectionBatch)
    if user.role=="USER":stmt=stmt.where(DetectionBatch.owner_id==user.id)
    if state:stmt=stmt.where(DetectionBatch.state==state)
    if created_from:stmt=stmt.where(DetectionBatch.created_at>=created_from)
    if created_to:stmt=stmt.where(DetectionBatch.created_at<created_to)
    out=paginate(db,stmt.order_by(DetectionBatch.created_at.desc()),page,page_size,lambda x:batch_out(db,x));db.commit()
    return result(request,out)
@router.get("/batches/{batch_id}")
def batch_detail(batch_id:UUID,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    out=batch_out(db,batch_access(db,user,batch_id),True);db.commit();return result(request,out)
@router.post("/batches/{batch_id}/cancel")
def batch_cancel(batch_id:UUID,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"detection.image")
    batch=batch_access(db,user,batch_id)
    if batch.state=="COMPLETED":raise ApiError(409,"TASK_ALREADY_TERMINAL","批次已经完成")
    batch.cancel_requested=True
    db.execute(update(Detection).where(Detection.batch_id==batch.id,Detection.state.in_(["PENDING","QUEUED"])).values(state="CANCELLED",finished_at=now()))
    db.flush();out=batch_out(db,batch,True);db.commit();return result(request,out)
@router.put("/{detection_id}/review")
def review(detection_id:UUID,payload:ReviewIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);row=detection_access(db,user,str(detection_id),True)
    version(db,row,payload.expected_version);before={"review_status":row.review_status};row.review_status=payload.review_status
    history(db,request,user,row,"REVIEW",payload.comment,before,{"review_status":row.review_status});db.commit()
    return result(request,detection_out(row))
def history(db,request,user,row,type,comment,before,after):
    db.add(DetectionHistory(detection_id=row.id,actor_id=user.id,type=type,comment=comment,before=before,after=after,record_version=row.version))
    audit(db,request,user,"DETECTION_"+type,"DETECTION",row.id,before,after)
@router.get("/{detection_id}/history")
def histories(detection_id:UUID,request:Request,page:int=1,page_size:int=20,db:Session=Depends(get_db),user=Depends(require_user)):
    row=detection_access(db,user,str(detection_id))
    return result(request,paginate(db,select(DetectionHistory).where(DetectionHistory.detection_id==row.id).order_by(DetectionHistory.created_at.desc()),page,page_size,lambda x:fields(x,"id type actor_id created_at comment before after record_version")))
def box_access(row,id):
    box=next((x for x in row.boxes if x.id==str(id)),None)
    if not box:raise ApiError(404,"NOT_FOUND","检测框不存在")
    return box
@router.put("/{detection_id}/boxes/{box_id}/person-link")
def link(detection_id:UUID,box_id:UUID,payload:LinkIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"person.read");row=detection_access(db,user,str(detection_id),True);box=box_access(row,box_id)
    person=db.get(Person,str(payload.person_id))
    if not person or person.status!="ACTIVE":raise ApiError(409,"PERSON_NOT_ACTIVE","只能关联启用中的档案")
    version(db,row,payload.expected_version);before=box.person_link or {}
    box.person_link={"person_id":person.id,"person_code_snapshot":person.person_code,"name_snapshot":person.name,"linked_by":user.id,"linked_at":now().isoformat()}
    history(db,request,user,row,"REPLACE" if before else "LINK",payload.comment,before,box.person_link);db.commit()
    return result(request,{"box":next(x for x in detection_out(row).boxes if x.id==box.id),"record_version":row.version})
@router.delete("/{detection_id}/boxes/{box_id}/person-link")
def unlink(detection_id:UUID,box_id:UUID,request:Request,if_match:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"person.read");row=detection_access(db,user,str(detection_id),True);box=box_access(row,box_id)
    version(db,row,match_version(if_match));before=box.person_link or {};box.person_link=None
    history(db,request,user,row,"UNLINK","解除人工关联",before,{});db.commit()
    return result(request,{"box":next(x for x in detection_out(row).boxes if x.id==box.id),"record_version":row.version})
@router.delete("/{detection_id}",status_code=204)
def delete(detection_id:UUID,request:Request,if_match:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user);row=detection_access(db,user,str(detection_id))
    if row.state not in {"SUCCEEDED","FAILED","CANCELLED"}:raise ApiError(409,"TASK_NOT_TERMINAL","不能删除未结束任务")
    version(db,row,match_version(if_match));row.deleted_at=now();audit(db,request,user,"DETECTION_DELETED","DETECTION",row.id);db.commit()
    return Response(status_code=204)
