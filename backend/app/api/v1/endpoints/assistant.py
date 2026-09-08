"""Consent-gated assistant conversations and cloud text request lifecycle."""

import asyncio
from datetime import UTC, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from sqlalchemy import func, select, update
from app.models.extension import AgentProfile
from sqlalchemy.orm import Session, selectinload

from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from app.core.errors import request_id
from app.db.session import get_db
from app.models import (
    AssistantConversation, AssistantMessage, AssistantRequest, Detection, KnowledgeDocument, KnowledgeChunk,
    LlmSettings, ProviderCallLedger, ProviderConfig, User,
)
from app.schemas.common import SuccessResponse
from app.schemas.llm import AssistantConversationCreate, ConfirmRequestIn, PrepareRequestIn
from app.services.llm import (
    SYSTEM_TEMPLATE, accessible_detection, assistant_permission, canonical_hash, detection_evidence,
    history_for, make_outbound, retrieve_knowledge, run_request, sources_still_available, source_visible, validation_fingerprint,
)
from app.services.security import ApiError, now, require_csrf, require_user
from app.services.assistant_output import PROMPT_VERSION, detection_snapshot, output_instruction

router = APIRouter(prefix="/assistant", tags=["assistant"])


def conversation_or_404(db: Session, conversation_id: str, user: User) -> AssistantConversation:
    item = db.get(AssistantConversation, conversation_id)
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "助手会话不存在")
    return item


def select_provider(db: Session, provider_config_id: str | None) -> ProviderConfig:
    if provider_config_id:
        config = db.get(ProviderConfig, provider_config_id)
    else:
        settings = db.get(LlmSettings, 1)
        config = db.get(ProviderConfig, settings.default_provider_config_id) if settings and settings.default_provider_config_id else None
    if config is None or not config.enabled or config.validation_fingerprint != validation_fingerprint(config):
        raise ApiError(409, "LLM_NOT_CONFIGURED", "没有可用的已验证云端文本服务")
    return config


def request_out(item: AssistantRequest, include_preview: bool = False) -> dict:
    result = {
        "agent_profile_id":item.agent_profile_id,"agent_version":item.agent_version,"agent_name_snapshot":item.agent_name_snapshot,"prompt_template_version":item.prompt_template_version,"delivery_mode":item.delivery_mode,
        "id": item.id, "conversation_id": item.conversation_id, "mode": item.mode, "state": item.state,
        "provider": item.provider, "provider_config_id": item.provider_config_id, "provider_version": item.provider_version,
        "model": item.model, "payload_hash": item.payload_hash, "source_refs": item.source_refs,
        "expires_at": item.expires_at, "consented_at": item.consented_at, "answer": item.answer,
        "is_partial": item.is_partial, "citations": item.citations, "warning_codes": item.warning_codes,
        "usage": item.usage, "billing_state": item.billing_state, "error_code": item.error_code,
        "created_at": item.created_at, "finished_at": item.finished_at,
    }
    if include_preview:
        result["outbound_preview"] = item.outbound_payload["preview"]
        result["requires_consent"] = True
    return result


def message_visible(db: Session, message: AssistantMessage, user: User) -> bool:
    return all(source_visible(db,source,user) for source in message.source_refs)


# Provider selection is intentionally retired in V1.2; choose an agent explicitly.
def available_providers(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[list[dict]]:
    assistant_permission(user)
    settings = db.get(LlmSettings, 1)
    rows = list(db.scalars(select(ProviderConfig).where(ProviderConfig.enabled.is_(True)).order_by(ProviderConfig.name, ProviderConfig.id)))
    data = [{"id": item.id, "provider": item.provider, "name": item.name, "model": item.model,
             "is_default": bool(settings and settings.default_provider_config_id == item.id)}
            for item in rows if item.validation_fingerprint == validation_fingerprint(item)]
    return SuccessResponse(data=data, request_id=request_id(request))


@router.get("/conversations", response_model=SuccessResponse[dict])
def list_conversations(request: Request, page: int = 1, page_size: int = 20,
                       db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    assistant_permission(user)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    rows = list(db.scalars(select(AssistantConversation).where(AssistantConversation.owner_id == user.id).order_by(
        AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())))
    data = [{"id": item.id, "title": item.title, "created_at": item.created_at} for item in rows[(page - 1) * page_size:page * page_size]]
    return SuccessResponse(data={"items": data, "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.post("/conversations", status_code=201, response_model=SuccessResponse[dict])
def create_conversation(payload: AssistantConversationCreate, request: Request, response: Response,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                        db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    assistant_permission(user)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, user, request, idempotency_key, serialized)
    if replay:
        response.status_code, response.headers["Idempotency-Replayed"] = replay.response_status, "true"
        return SuccessResponse(data=replay.response_data, request_id=request_id(request))
    conversation = AssistantConversation(owner_id=user.id, title=payload.title)
    db.add(conversation)
    db.flush()
    data = {"id": conversation.id, "title": conversation.title, "created_at": conversation.created_at}
    remember_idempotency(db, user, request, idempotency_key or "", serialized, 201, data)
    db.commit()
    return SuccessResponse(data=data, request_id=request_id(request))


@router.get("/conversations/{conversation_id}/messages", response_model=SuccessResponse[dict])
def list_messages(conversation_id: UUID, request: Request, page: int = 1, page_size: int = 20, agent_profile_id:UUID|None=None,
                  db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    assistant_permission(user)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    conversation_or_404(db, str(conversation_id), user)
    statement=select(AssistantMessage).join(AssistantRequest,AssistantMessage.request_id==AssistantRequest.id).where(AssistantMessage.conversation_id==str(conversation_id))
    if agent_profile_id:statement=statement.where(AssistantRequest.agent_profile_id==str(agent_profile_id))
    rows = list(db.scalars(statement.order_by(
        AssistantMessage.created_at.desc(), AssistantMessage.id.desc())))
    items = []
    for item in rows[(page - 1) * page_size:page * page_size]:
        if not message_visible(db, item, user):
            items.append({"id": item.id, "request_id": item.request_id, "hidden": True, "reason": "SOURCE_ACCESS_REVOKED"})
        else:
            source_request=db.get(AssistantRequest,item.request_id)
            items.append({"id": item.id, "request_id": item.request_id, "role": item.role, "content": item.content,
                          "agent_profile_id":source_request.agent_profile_id,"agent_name_snapshot":source_request.agent_name_snapshot,
                          "citations": item.citations, "is_partial": item.is_partial, "created_at": item.created_at, "hidden": False})
    return SuccessResponse(data={"items": items, "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.post("/requests/prepare", status_code=201, response_model=SuccessResponse[dict])
def prepare_request(payload: PrepareRequestIn, request: Request, response: Response,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    assistant_permission(user)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, user, request, idempotency_key, serialized)
    if replay:
        response.status_code, response.headers["Idempotency-Replayed"] = replay.response_status, "true"
        existing=db.get(AssistantRequest,replay.response_data['id'])
        if not existing or existing.owner_id!=user.id or not sources_still_available(db,existing,user):
            raise ApiError(403,'SOURCE_ACCESS_REVOKED','原准备单来源权限已变化，不能重放旧预览')
        return SuccessResponse(data=request_out(existing,include_preview=existing.state=='PREPARED'), request_id=request_id(request))
    conversation = conversation_or_404(db, payload.conversation_id, user)
    from app.api.v1.endpoints.agents import available,validate_agent
    agent=db.get(AgentProfile,payload.agent_profile_id)
    if not available(db,agent):raise ApiError(409,"AGENT_UNAVAILABLE","所选智能体或其关联厂商不可用")
    validate_agent(db,agent)
    config = select_provider(db, agent.provider_config_id)
    active_prepared = db.scalar(select(func.count()).select_from(AssistantRequest).where(
        AssistantRequest.owner_id == user.id, AssistantRequest.state == "PREPARED", AssistantRequest.expires_at > now())) or 0
    if active_prepared >= 5:
        raise ApiError(429, "LLM_LIMIT_REACHED", "未确认的准备单已达到上限")
    source_refs: list[dict] = []
    evidence_parts: list[str] = []
    fact_snapshots: list[dict] = []
    if payload.mode in {"SUMMARY", "REPORT"}:
        for index, detection_id in enumerate(payload.detection_ids, start=1):
            item = accessible_detection(db, user, detection_id)
            label = f"D{index}"
            source_refs.append({"type": "DETECTION", "id": item.id, "version": item.version, "label": label})
            snapshot,encoded=detection_snapshot(item,label)
            fact_snapshots.append(snapshot)
            evidence_parts.append(encoded)
    elif payload.mode == "KNOWLEDGE":
        matches = retrieve_knowledge(db, payload.question)
        if not matches:
            raise ApiError(422, "SOURCE_INSUFFICIENT", "没有足够的业务资料可用于回答，请调整问题或改用普通问答")
        for index, (document, chunk) in enumerate(matches, start=1):
            label = f"K{index}"
            source_refs.append({"type": "KNOWLEDGE", "id": document.id, "version": document.version,
                                "chunk_id": chunk.id, "chunk_hash": chunk.content_sha256, "label": label, "title": document.title})
            evidence_parts.append(f"[{label}] 标题：{document.title}\n{chunk.content}\n[/{label}]")
    history = history_for(db, conversation,agent.id)
    outbound = make_outbound(SYSTEM_TEMPLATE+'\n'+output_instruction(payload.mode), history, payload.question, "\n\n".join(evidence_parts))
    outbound['fact_snapshots']=fact_snapshots
    business="业务角色要求（低于固定安全约束；不赋予执行权）：\n"+agent.business_prompt
    outbound["messages"].insert(1,{"role":"user","content":business})
    outbound["preview"]["business_prompt_text"]=business
    outbound["preview"]["messages"]=outbound["messages"]
    outbound["temperature"]=agent.temperature
    delivery="GENERAL_DELTA" if payload.mode=="GENERAL" and config.capabilities.get("supports_stream") else "VALIDATED_FINAL" if config.capabilities.get("supports_stream") else "BUFFERED_FINAL"
    outbound["configuration"]={"agent_profile_id":agent.id,"agent_version":agent.version,"provider_version":config.version,"model":config.model,"temperature":agent.temperature,"max_tokens":config.max_output_tokens,"delivery_mode":delivery,"prompt_template_version":PROMPT_VERSION}
    outbound["preview"]["configuration"]=outbound["configuration"]
    if len("".join(str(message["content"]) for message in outbound["messages"])) > 12000:
        raise ApiError(422, "CONTEXT_TOO_LARGE", "待发送文本超过上限，请减少内容")
    item = AssistantRequest(conversation_id=conversation.id, owner_id=user.id, mode=payload.mode, state="PREPARED",
                            agent_profile_id=agent.id,agent_version=agent.version,agent_name_snapshot=agent.name,delivery_mode=delivery,prompt_template_version=PROMPT_VERSION,
                            provider_config_id=config.id, provider_version=config.version, provider=config.provider, model=config.model,
                            payload_hash=canonical_hash(outbound), outbound_payload=outbound, source_refs=source_refs,
                            conversation_context_version=conversation.context_version, expires_at=now() + timedelta(minutes=5),
                            warning_codes=["CLOUD_TEXT_TRANSFER", "GENERATED_CONTENT"])
    db.add(item)
    db.flush()
    data = request_out(item, include_preview=True)
    remember_idempotency(db, user, request, idempotency_key or "", serialized, 201, data)
    db.commit()
    return SuccessResponse(data=data, request_id=request_id(request))


@router.post("/requests/{assistant_request_id}/confirm", status_code=202, response_model=SuccessResponse[dict])
def confirm_request(assistant_request_id: UUID, payload: ConfirmRequestIn, request: Request, background_tasks: BackgroundTasks,
                    db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    assistant_permission(user)
    item = db.get(AssistantRequest, str(assistant_request_id))
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "助手请求不存在")
    if item.state != "PREPARED":
        return SuccessResponse(data={"id": item.id, "state": item.state}, request_id=request_id(request))
    if item.expires_at.replace(tzinfo=UTC) <= now():
        item.state, item.finished_at = "EXPIRED", now()
        db.commit()
        raise ApiError(410, "PREPARATION_EXPIRED", "准备单已过期，请重新准备")
    if item.payload_hash != payload.payload_hash:
        raise ApiError(412, "CONTEXT_CHANGED", "待发送内容已变化，请重新准备")
    config = db.get(ProviderConfig, item.provider_config_id)
    agent=db.get(AgentProfile,item.agent_profile_id) if item.agent_profile_id else None
    conversation = db.get(AssistantConversation, item.conversation_id)
    if (agent is None or agent.status!="ACTIVE" or agent.version!=item.agent_version or config is None or config.version != item.provider_version or not config.enabled or config.validation_fingerprint!=validation_fingerprint(config) or
            not sources_still_available(db, item, user) or conversation is None or conversation.context_version != item.conversation_context_version):
        item.state, item.error_code, item.finished_at = "EXPIRED", "CONTEXT_CHANGED", now()
        db.commit()
        raise ApiError(412, "CONTEXT_CHANGED", "来源、会话或厂商配置已变化，请重新准备")
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    sent = db.scalar(select(func.count()).select_from(AssistantRequest).where(
        AssistantRequest.provider_config_id == config.id, AssistantRequest.consented_at >= today,
        AssistantRequest.state.in_(["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]))) or 0
    tests = db.scalar(select(func.count()).select_from(ProviderCallLedger).where(
        ProviderCallLedger.provider_config_id == config.id, ProviderCallLedger.created_at >= today)) or 0
    user_active = db.scalar(select(func.count()).select_from(AssistantRequest).where(
        AssistantRequest.owner_id == user.id, AssistantRequest.state.in_(["QUEUED", "RUNNING"]))) or 0
    globally_active = db.scalar(select(func.count()).select_from(AssistantRequest).where(
        AssistantRequest.state.in_(["QUEUED", "RUNNING"]))) or 0
    # Two calls may run and eight more may wait. This is deliberately a
    # bounded queue rather than an unbounded background-task accumulator.
    if sent + tests >= config.daily_request_limit or user_active >= 1 or globally_active >= 10:
        raise ApiError(429, "LLM_LIMIT_REACHED", "云端调用配额或并发上限已达到")
    accepted=db.execute(update(AssistantRequest).where(AssistantRequest.id==item.id,AssistantRequest.state=="PREPARED").values(state="QUEUED",consented_at=now()).execution_options(synchronize_session=False)).rowcount
    db.commit()
    if accepted:background_tasks.add_task(run_request, request.app, item.id)
    db.refresh(item)
    return SuccessResponse(data={"id": item.id, "state": item.state}, request_id=request_id(request))


@router.get("/requests/{assistant_request_id}", response_model=SuccessResponse[dict])
def get_request(assistant_request_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    assistant_permission(user)
    item = db.get(AssistantRequest, str(assistant_request_id))
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "助手请求不存在")
    if not sources_still_available(db, item, user):
        raise ApiError(403, "SOURCE_ACCESS_REVOKED", "相关来源当前已不可访问")
    return SuccessResponse(data=request_out(item), request_id=request_id(request))


@router.get("/requests/{assistant_request_id}/citations/{label}", response_model=SuccessResponse[dict])
def get_citation(assistant_request_id: UUID, label: str, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_user)):
    assistant_permission(user)
    item=db.get(AssistantRequest,str(assistant_request_id))
    if not item or item.owner_id!=user.id or item.state!='SUCCEEDED':
        raise ApiError(404,'NOT_FOUND','引用不存在')
    if not sources_still_available(db,item,user):
        raise ApiError(403,'SOURCE_ACCESS_REVOKED','来源已变化，旧答复及引用不再可见')
    if not any(x['label']==label for x in item.citations):
        raise ApiError(404,'NOT_FOUND','本次答复未引用该来源')
    source=next(x for x in item.source_refs if x['label']==label)
    data={'label':label,'type':source['type'],'id':source['id'],'version':source['version']}
    if source['type']=='KNOWLEDGE':
        document=db.get(KnowledgeDocument,source['id']);chunk=db.get(KnowledgeChunk,source['chunk_id'])
        data.update(title=document.title,content=chunk.content,chunk_hash=chunk.content_sha256)
    else:
        row=accessible_detection(db,user,source['id'])
        snapshot,_=detection_snapshot(row,label)
        data.update(title='检测记录 '+row.id,facts=snapshot,detail_route='records/'+row.id)
    return SuccessResponse(data=data,request_id=request_id(request))


@router.post("/requests/{assistant_request_id}/cancel", response_model=SuccessResponse[dict])
def cancel_request(assistant_request_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    assistant_permission(user)
    item = db.get(AssistantRequest, str(assistant_request_id))
    if item is None or item.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "助手请求不存在")
    if item.state not in {"PREPARED", "QUEUED", "RUNNING"}:
        raise ApiError(409, "TASK_ALREADY_TERMINAL", "请求已经结束")
    item.state, item.finished_at = "CANCELLED", now()
    if item.billing_state == "UNKNOWN":
        item.warning_codes = [*item.warning_codes, "CANCELLATION_MAY_BE_BILLED"]
    db.commit()
    return SuccessResponse(data=request_out(item), request_id=request_id(request))
