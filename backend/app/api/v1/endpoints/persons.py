from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import Field, model_validator
from app.db.session import get_db
from app.models import Media
from app.models.extension import Person
from app.schemas.auth import StrictModel
from app.services.security import require_user, require_csrf, require_manager, ApiError, now
from app.services.business import allow, audit, fields, match_version, paginate, result, version
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency

router=APIRouter(prefix="/persons",tags=["persons"])
class PersonCreate(StrictModel):
    person_code:str=Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    name:str=Field(min_length=1,max_length=50)
    photo_media_id:UUID|None=None
    attention_note:str=Field(default="",max_length=1000)
    status:Literal["ACTIVE","INACTIVE"]="ACTIVE"
class PersonPatch(StrictModel):
    name:str|None=Field(default=None,min_length=1,max_length=50)
    photo_media_id:UUID|None=None
    attention_note:str|None=Field(default=None,max_length=1000)
    status:Literal["ACTIVE","INACTIVE"]|None=None
    expected_version:int=Field(ge=1)
    @model_validator(mode="after")
    def changes(self):
        if self.model_fields_set=={"expected_version"}: raise ValueError("至少修改一个字段")
        return self
def output(row):
    return {**fields(row,"id person_code name photo_media_id attention_note status version created_at updated_at"),"is_demo":True}
def lookup(db, id):
    row=db.get(Person,str(id))
    if not row or row.status=="DELETED": raise ApiError(404,"NOT_FOUND","档案不存在")
    return row
def bind_photo(db,user,id):
    media=db.get(Media,str(id))
    if not media or media.owner_id!=user.id or media.purpose!="PERSON_PHOTO" or media.state!="STAGED" or (media.expires_at and media.expires_at.replace(tzinfo=now().tzinfo)<=now()):
        raise ApiError(422,"MEDIA_BINDING_INVALID","请选择本人上传且未绑定的有效档案照片")
    media.state="BOUND"
    return media.id
@router.get("")
def listing(request:Request,page:int=1,page_size:int=20,q:str|None=None,status:Literal["ACTIVE","INACTIVE"]|None=None,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"person.read")
    stmt=select(Person).where(Person.status!="DELETED")
    if status:stmt=stmt.where(Person.status==status)
    if q:stmt=stmt.where(Person.name.contains(q,autoescape=True)|Person.person_code.contains(q,autoescape=True))
    return result(request,paginate(db,stmt.order_by(Person.created_at.desc(),Person.id.desc()),page,page_size,output))
@router.get("/{person_id}")
def detail(person_id:UUID,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"person.read")
    return result(request,output(lookup(db,person_id)))
@router.post("",status_code=201)
def create(payload:PersonCreate,request:Request,response:Response,idempotency_key:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user)
    data=payload.model_dump(mode="json")
    replay=idempotency_replay(db,user,request,idempotency_key,data)
    if replay:
        response.headers["Idempotency-Replayed"]="true"
        return result(request,replay.response_data)
    if db.scalar(select(Person).where(Person.person_code==payload.person_code)):raise ApiError(409,"PERSON_CODE_EXISTS","档案编号已存在，不可复用")
    if payload.photo_media_id:data["photo_media_id"]=bind_photo(db,user,payload.photo_media_id)
    row=Person(**data);db.add(row);db.flush()
    from fastapi.encoders import jsonable_encoder
    out=jsonable_encoder(output(row))
    audit(db,request,user,"PERSON_CREATED","PERSON",row.id)
    remember_idempotency(db,user,request,idempotency_key,data,201,out);db.commit()
    return result(request,out)
@router.patch("/{person_id}")
def patch(person_id:UUID,payload:PersonPatch,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user)
    row=lookup(db,person_id);version(db,row,payload.expected_version)
    for k,v in payload.model_dump(exclude_unset=True,exclude={"expected_version"},mode="json").items():
        if k=="photo_media_id" and v:v=bind_photo(db,user,v)
        if v is None and k!="photo_media_id":raise ApiError(422,"VALIDATION_ERROR","该字段不可为空")
        setattr(row,k,v)
    audit(db,request,user,"PERSON_UPDATED","PERSON",row.id);db.commit()
    return result(request,output(row))
@router.delete("/{person_id}",status_code=204)
def delete(person_id:UUID,request:Request,if_match:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user)
    row=lookup(db,person_id);version(db,row,match_version(if_match));row.status="DELETED"
    audit(db,request,user,"PERSON_DELETED","PERSON",row.id);db.commit()
    return Response(status_code=204)
