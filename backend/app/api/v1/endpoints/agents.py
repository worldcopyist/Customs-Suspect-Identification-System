"""Configurable text roles, never executable agents or permission grants."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import Field
from app.db.session import get_db
from app.models import ProviderConfig, LlmSettings
from app.models.extension import AgentProfile
from app.schemas.auth import StrictModel
from app.services.security import require_user, require_csrf, require_manager, ApiError
from app.services.business import allow, audit, fields, result, paginate, version, match_version
from app.services.llm import validation_fingerprint
from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
router=APIRouter(tags=["agents"])
class AgentCreate(StrictModel):
    name:str=Field(min_length=1,max_length=100)
    description:str=Field(default="",max_length=500)
    business_prompt:str=Field(min_length=1,max_length=4000)
    temperature:float|None=Field(ge=0,le=2)
    provider_config_id:UUID
    status:Literal["ACTIVE","INACTIVE"]="INACTIVE"
class AgentPatch(StrictModel):
    name:str|None=Field(default=None,min_length=1,max_length=100)
    description:str|None=Field(default=None,max_length=500)
    business_prompt:str|None=Field(default=None,min_length=1,max_length=4000)
    temperature:float|None=Field(default=None,ge=0,le=2)
    provider_config_id:UUID|None=None
    status:Literal["ACTIVE","INACTIVE"]|None=None
    expected_version:int=Field(ge=1)
class DefaultIn(StrictModel):
    default_agent_profile_id:UUID|None
    expected_version:int=Field(ge=1)
def settings(db):
    row=db.get(LlmSettings,1)
    if not row:row=LlmSettings(id=1);db.add(row);db.flush()
    return row
def available(db,agent):
    if not agent or agent.status!="ACTIVE":return False
    p=db.get(ProviderConfig,agent.provider_config_id)
    if not (p and p.enabled and p.capabilities and p.validation_fingerprint==validation_fingerprint(p)):return False
    caps=p.capabilities
    if caps.get("supports_temperature"):
        return agent.temperature is not None and caps.get("temperature_min",0)<=agent.temperature<=caps.get("temperature_max",2)
    return agent.temperature is None
def validate_agent(db,agent):
    p=db.get(ProviderConfig,agent.provider_config_id)
    if not p:raise ApiError(422,"PROVIDER_NOT_ENABLED","请选择存在的厂商配置")
    if agent.status=="ACTIVE" and not available(db,agent):raise ApiError(422,"PROVIDER_NOT_ENABLED","启用前需要测试并启用关联厂商")
    caps=p.capabilities
    if caps:
        if caps["supports_temperature"]:
            if agent.temperature is None or not caps["temperature_min"]<=agent.temperature<=caps["temperature_max"]:raise ApiError(422,"UNSUPPORTED_AGENT_PARAMETER","温度超出该模型已验证能力范围")
        elif agent.temperature is not None:raise ApiError(422,"UNSUPPORTED_AGENT_PARAMETER","此模型不支持温度，请置空")
def out(row):return fields(row,"id name description business_prompt temperature provider_config_id status version created_by created_at updated_at")
def lookup(db,id):
    row=db.get(AgentProfile,str(id))
    if not row or row.status=="ARCHIVED":raise ApiError(404,"NOT_FOUND","智能体不存在")
    return row
@router.get("/assistant/agents")
def public(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"assistant.use");default=settings(db).default_agent_profile_id
    rows=list(db.scalars(select(AgentProfile).where(AgentProfile.status=="ACTIVE").order_by(AgentProfile.created_at)))
    data={"items":[{"id":x.id,"name":x.name,"description":x.description,"is_default":x.id==default,"available":available(db,x)} for x in rows],"default_agent_profile_id":default};db.commit();return result(request,data)
@router.get("/admin/assistant/agents")
def listing(request:Request,page:int=1,page_size:int=20,q:str|None=None,status:Literal["ACTIVE","INACTIVE","ARCHIVED"]|None=None,db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);stmt=select(AgentProfile).where(AgentProfile.status==status if status else AgentProfile.status!="ARCHIVED")
    if q:stmt=stmt.where(AgentProfile.name.contains(q,autoescape=True))
    return result(request,paginate(db,stmt.order_by(AgentProfile.created_at.desc()),page,page_size,out))
@router.post("/admin/assistant/agents",status_code=201)
def create(payload:AgentCreate,request:Request,response:Response,idempotency_key:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user);data=payload.model_dump(mode="json")
    replay=idempotency_replay(db,user,request,idempotency_key,data)
    if replay:return result(request,replay.response_data)
    row=AgentProfile(**data,created_by=user.id);validate_agent(db,row);db.add(row);db.flush()
    from fastapi.encoders import jsonable_encoder
    serialized=jsonable_encoder(out(row));remember_idempotency(db,user,request,idempotency_key,data,201,serialized);audit(db,request,user,"AGENT_CREATED","AGENT",row.id);db.commit()
    return result(request,serialized)
@router.patch("/admin/assistant/agents/{agent_id}")
def patch(agent_id:UUID,payload:AgentPatch,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user);row=lookup(db,agent_id)
    if payload.status=="INACTIVE" and settings(db).default_agent_profile_id==row.id:raise ApiError(409,"DEFAULT_AGENT_PROTECTED","请先更换或清空默认智能体")
    version(db,row,payload.expected_version)
    for k,v in payload.model_dump(mode="json",exclude_unset=True,exclude={"expected_version"}).items():
        if v is None and k!="temperature":raise ApiError(422,"VALIDATION_ERROR","该字段不可为空")
        setattr(row,k,v)
    validate_agent(db,row);audit(db,request,user,"AGENT_UPDATED","AGENT",row.id,after={"version":row.version});db.commit();return result(request,out(row))
@router.delete("/admin/assistant/agents/{agent_id}",status_code=204)
def archive(agent_id:UUID,request:Request,if_match:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user);row=lookup(db,agent_id)
    if settings(db).default_agent_profile_id==row.id:raise ApiError(409,"DEFAULT_AGENT_PROTECTED","请先清空默认智能体")
    version(db,row,match_version(if_match));row.status="ARCHIVED";audit(db,request,user,"AGENT_ARCHIVED","AGENT",row.id);db.commit();return Response(status_code=204)
@router.get("/admin/settings/assistant")
def default(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_manager(user);row=settings(db);db.commit();return result(request,fields(row,"default_agent_profile_id version"))
@router.put("/admin/settings/assistant")
def set_default(payload:DefaultIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);require_manager(user);row=settings(db)
    if payload.default_agent_profile_id and not available(db,lookup(db,payload.default_agent_profile_id)):raise ApiError(422,"AGENT_NOT_ACTIVE","请选择可用的启用角色")
    version(db,row,payload.expected_version);row.default_agent_profile_id=str(payload.default_agent_profile_id) if payload.default_agent_profile_id else None
    audit(db,request,user,"DEFAULT_AGENT_UPDATED","SETTINGS","assistant",after={"agent_id":row.default_agent_profile_id});db.commit();return result(request,fields(row,"default_agent_profile_id version"))
