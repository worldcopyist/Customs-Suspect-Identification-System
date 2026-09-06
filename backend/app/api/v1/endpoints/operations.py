"""Administrator-only cloud provider and local knowledge management."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.chat import idempotency_replay, remember_idempotency
from app.core.errors import request_id
from app.db.session import get_db
from app.models import AssistantRequest, IdempotencyRecord, KnowledgeDocument, LlmSettings, ProviderCallLedger, ProviderConfig, User
from app.schemas.common import SuccessResponse
from app.schemas.llm import (
    KnowledgeCreate, KnowledgeOut, KnowledgePatch, LlmSettingsIn, ProviderConfigCreate,
    ProviderConfigOut, ProviderConfigPatch, ProviderTestIn,
)
from app.services.llm import (
    decrypt_secret, encrypt_secret, provider_generate, provider_out, replace_chunks, secret_fingerprint,
    validate_provider_url, validation_fingerprint,
)
from app.services.security import ApiError, now, require_csrf, require_manager, require_user
from app.services.business import audit,version,match_version

router = APIRouter(tags=["operations"])


def manager(user: User) -> None:
    require_manager(user)


def provider_or_404(db: Session, provider_config_id: str) -> ProviderConfig:
    config = db.get(ProviderConfig, provider_config_id)
    if config is None:
        raise ApiError(404, "NOT_FOUND", "厂商配置不存在")
    return config


def knowledge_or_404(db: Session, document_id: str) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if document is None or document.status=="DELETED":
        raise ApiError(404, "NOT_FOUND", "实训资料不存在")
    return document


def knowledge_out(document: KnowledgeDocument) -> KnowledgeOut:
    return KnowledgeOut(id=document.id, title=document.title, content=document.content, status=document.status,
                        version=document.version, created_at=document.created_at, updated_at=document.updated_at)


@router.get("/admin/llm/providers", response_model=SuccessResponse[dict])
def list_provider_configs(request: Request, page: int = 1, page_size: int = 20,
                          db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    manager(user)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    rows = list(db.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at.desc(), ProviderConfig.id.desc())))
    items = [provider_out(row) for row in rows[(page - 1) * page_size: page * page_size]]
    return SuccessResponse(data={"items": items, "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.post("/admin/llm/providers", status_code=201, response_model=SuccessResponse[ProviderConfigOut])
def create_provider_config(payload: ProviderConfigCreate, request: Request, response: Response,
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                           db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[ProviderConfigOut]:
    require_csrf(request, db)
    manager(user)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, user, request, idempotency_key, serialized)
    if replay:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = replay.response_status
        return SuccessResponse(data=ProviderConfigOut(**replay.response_data), request_id=request_id(request))
    if payload.enabled:
        raise ApiError(422, "PROVIDER_NOT_VALIDATED", "新配置必须先完成连接测试后才能启用")
    config = ProviderConfig(provider=payload.provider, name=payload.name.strip(),
                            base_url=validate_provider_url(payload.provider, payload.base_url), model=payload.model.strip(),
                            api_key_encrypted=encrypt_secret(payload.api_key), api_key_fingerprint=secret_fingerprint(payload.api_key),
                            enabled=False, max_output_tokens=payload.max_output_tokens, temperature=payload.temperature, timeout_seconds=payload.timeout_seconds,
                            daily_request_limit=payload.daily_request_limit)
    db.add(config)
    db.flush()
    data = provider_out(config)
    remember_idempotency(db, user, request, idempotency_key or "", serialized, 201, data)
    audit(db,request,user,'PROVIDER_CREATED','PROVIDER',config.id)
    db.commit()
    return SuccessResponse(data=ProviderConfigOut(**data), request_id=request_id(request))


@router.patch("/admin/llm/providers/{provider_config_id}", response_model=SuccessResponse[ProviderConfigOut])
def update_provider_config(provider_config_id: UUID, payload: ProviderConfigPatch, request: Request,
                           db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[ProviderConfigOut]:
    require_csrf(request, db)
    manager(user)
    config = provider_or_404(db, str(provider_config_id))
    version(db,config,payload.expected_version)
    protocol_changed = False
    for field in ("name", "model", "max_output_tokens", "temperature", "daily_request_limit"):
        value = getattr(payload, field)
        if value is not None:
            if field in {"model", "max_output_tokens", "temperature"} and value != getattr(config, field):
                protocol_changed = True
            setattr(config, field, value.strip() if isinstance(value, str) else value)
    if payload.base_url is not None:
        base_url = validate_provider_url(config.provider, payload.base_url)
        protocol_changed = protocol_changed or base_url != config.base_url
        config.base_url = base_url
    if payload.api_key is not None:
        config.api_key_encrypted, config.api_key_fingerprint = encrypt_secret(payload.api_key), secret_fingerprint(payload.api_key)
        protocol_changed = True
    if payload.enabled is not None:
        if payload.enabled and config.validation_fingerprint != validation_fingerprint(config):
            raise ApiError(422, "PROVIDER_NOT_VALIDATED", "当前服务地址、模型或密钥尚未通过连接测试")
        config.enabled = payload.enabled
    if protocol_changed:
        config.validation_fingerprint, config.validated_at = None, None
        if config.enabled:
            config.enabled = False
    audit(db,request,user,'PROVIDER_UPDATED','PROVIDER',config.id,after={'version':config.version,'enabled':config.enabled})
    db.commit()
    return SuccessResponse(data=ProviderConfigOut(**provider_out(config)), request_id=request_id(request))


@router.post("/admin/llm/providers/{provider_config_id}/test", response_model=SuccessResponse[dict])
async def test_provider_config(provider_config_id: UUID, payload: ProviderTestIn, request: Request,
                               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                               db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    manager(user)
    config = provider_or_404(db, str(provider_config_id))
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, user, request, idempotency_key, serialized)
    if replay:
        if replay.response_data.get("outcome_unknown"):
            raise ApiError(409, "OUTCOME_UNKNOWN", "前次连接测试结果未知，请明确发起新的测试")
        return SuccessResponse(data=replay.response_data, request_id=request_id(request))
    if config.version != payload.expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试")
    temperatures=list(dict.fromkeys([payload.temperature_min,payload.temperature_max]))
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    def call_count():
        sends=db.scalar(select(func.count()).select_from(AssistantRequest).where(
            AssistantRequest.provider_config_id==config.id,AssistantRequest.consented_at>=today,
            AssistantRequest.state.in_(["QUEUED","RUNNING","SUCCEEDED","FAILED","CANCELLED"]))) or 0
        tests=db.scalar(select(func.count()).select_from(ProviderCallLedger).where(
            ProviderCallLedger.provider_config_id==config.id,ProviderCallLedger.created_at>=today)) or 0
        return sends+tests
    if call_count()+len(temperatures)>config.daily_request_limit:
        raise ApiError(429,"LLM_LIMIT_REACHED","剩余配额不足以完成此次明确选择的测试")
    # Invalidate old assumptions before probing. Each real call gets a ledger entry;
    # the unknown marker prevents a timeout or lost response from triggering retries.
    version(db,config,payload.expected_version)
    config.enabled=False
    config.capabilities=None
    config.validation_fingerprint=None
    config.validated_at=None
    tested_version=config.version
    from types import SimpleNamespace
    frozen={k:getattr(config,k) for k in ("provider","base_url","model","api_key_encrypted","max_output_tokens","timeout_seconds")}
    remember_idempotency(db,user,request,idempotency_key or "",serialized,409,{"outcome_unknown":True})
    audit(db,request,user,"PROVIDER_TEST_STARTED","PROVIDER",config.id,after={"planned_calls":len(temperatures),"stream":payload.test_stream})
    db.commit()
    started=datetime.now(UTC)
    results=[]
    for temperature in temperatures:
        db.refresh(config)
        if config.version!=tested_version:
            raise ApiError(409,"VERSION_CONFLICT","测试期间配置已变化，停止剩余测试；已发出的请求可能计费")
        if call_count()>=config.daily_request_limit:
            raise ApiError(429,"LLM_LIMIT_REACHED","配额已达到，停止剩余测试")
        db.add(ProviderCallLedger(provider_config_id=config.id,kind="TEST"))
        db.commit()
        probe=SimpleNamespace(**frozen,temperature=temperature,capabilities={"supports_stream":payload.test_stream})
        generated=await provider_generate(probe,[{"role":"system","content":"你是课程实训文本助手。"},{"role":"user","content":"仅回复：连接测试成功。"}])
        if not generated.get("text") or generated.get("finish_reason")!="stop":
            raise ApiError(502,"PROVIDER_RESPONSE_INVALID","测试未返回完整正文，不能认证能力")
        results.append(generated)
    db.expire(config)
    # CAS makes concurrent edits invalidate this result; no API secret is returned.
    version(db,config,tested_version)
    config.capabilities={"supports_stream":payload.test_stream,"supports_temperature":payload.temperature_min is not None,
                         "temperature_min":payload.temperature_min,"temperature_max":payload.temperature_max,
                         "validation_method":"EXPLICIT_BOUNDARY_PROBES","tested_temperatures":temperatures}
    config.validation_fingerprint,config.validated_at=validation_fingerprint(config),now()
    data={"ok":True,"latency_ms":int((datetime.now(UTC)-started).total_seconds()*1000),"model":config.model,
          "test_call_count":len(results),"capabilities":config.capabilities,"version":config.version,
          "usage":[x["usage"] for x in results],"billing_state":"REPORTED" if all(x["usage"] for x in results) else "UNKNOWN"}
    record=db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.user_id==user.id,IdempotencyRecord.method==request.method,
                     IdempotencyRecord.path==request.url.path,IdempotencyRecord.key==(idempotency_key or "")))
    if record:record.response_status,record.response_data=200,data
    audit(db,request,user,"PROVIDER_TEST_COMPLETED","PROVIDER",config.id,after={"call_count":len(results),"version":config.version})
    db.commit()
    return SuccessResponse(data=data,request_id=request_id(request))


def llm_settings(db: Session) -> LlmSettings:
    settings = db.get(LlmSettings, 1)
    if settings is None:
        settings = LlmSettings(id=1)
        db.add(settings)
        db.flush()
    return settings


# Retired: V1.2 uses /admin/settings/assistant.
def get_llm_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    manager(user)
    settings = llm_settings(db)
    db.commit()
    return SuccessResponse(data={"default_provider_config_id": settings.default_provider_config_id, "version": settings.version}, request_id=request_id(request))


# Retired provider-only settings route.
def update_llm_settings(payload: LlmSettingsIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    manager(user)
    settings, config = llm_settings(db), provider_or_404(db, payload.default_provider_config_id)
    if settings.version != payload.expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "设置已更新，请刷新后重试", {"current_version": settings.version})
    if not config.enabled or config.validation_fingerprint != validation_fingerprint(config):
        raise ApiError(422, "PROVIDER_NOT_ENABLED", "默认厂商必须处于已验证启用状态")
    settings.default_provider_config_id, settings.version = config.id, settings.version + 1
    db.commit()
    return SuccessResponse(data={"default_provider_config_id": settings.default_provider_config_id, "version": settings.version}, request_id=request_id(request))


@router.get("/admin/knowledge/documents", response_model=SuccessResponse[dict])
def list_knowledge(request: Request, page: int = 1, page_size: int = 20, q: str | None = None, status: str | None = None,
                   db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[dict]:
    manager(user)
    if page < 1 or not 1 <= page_size <= 100 or status not in {None, "ACTIVE", "INACTIVE"}:
        raise ApiError(422, "VALIDATION_ERROR", "分页或筛选参数不合法")
    statement = select(KnowledgeDocument).where(KnowledgeDocument.status!="DELETED")
    if status:
        statement = statement.where(KnowledgeDocument.status == status)
    if q and q.strip():
        statement = statement.where(KnowledgeDocument.title.like(f"%{q.strip()}%"))
    rows = list(db.scalars(statement.order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())))
    items = [knowledge_out(row).model_dump(mode="json") for row in rows[(page - 1) * page_size:page * page_size]]
    return SuccessResponse(data={"items": items, "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.get("/admin/knowledge/documents/{document_id}", response_model=SuccessResponse[KnowledgeOut])
def get_knowledge(document_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[KnowledgeOut]:
    manager(user)
    return SuccessResponse(data=knowledge_out(knowledge_or_404(db, str(document_id))), request_id=request_id(request))


@router.post("/admin/knowledge/documents", status_code=201, response_model=SuccessResponse[KnowledgeOut])
def create_knowledge(payload: KnowledgeCreate, request: Request, response: Response,
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                     db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[KnowledgeOut]:
    require_csrf(request, db)
    manager(user)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, user, request, idempotency_key, serialized)
    if replay:
        response.status_code, response.headers["Idempotency-Replayed"] = replay.response_status, "true"
        return SuccessResponse(data=KnowledgeOut(**replay.response_data), request_id=request_id(request))
    active_count = db.scalar(select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.status == "ACTIVE")) or 0
    if payload.status == "ACTIVE" and active_count >= 100:
        raise ApiError(422, "KNOWLEDGE_LIMIT_REACHED", "启用资料已达到上限")
    document = KnowledgeDocument(title=payload.title.strip(), content=payload.content, status=payload.status)
    db.add(document)
    db.flush()
    replace_chunks(db, document)
    data = knowledge_out(document).model_dump(mode="json")
    remember_idempotency(db, user, request, idempotency_key or "", serialized, 201, data)
    audit(db,request,user,'KNOWLEDGE_CREATED','KNOWLEDGE',document.id)
    db.commit()
    return SuccessResponse(data=KnowledgeOut(**data), request_id=request_id(request))


@router.patch("/admin/knowledge/documents/{document_id}", response_model=SuccessResponse[KnowledgeOut])
def update_knowledge(document_id: UUID, payload: KnowledgePatch, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[KnowledgeOut]:
    require_csrf(request, db)
    manager(user)
    document = knowledge_or_404(db, str(document_id))
    version(db,document,payload.expected_version)
    content_changed = payload.content is not None
    if payload.title is not None: document.title = payload.title.strip()
    if payload.content is not None: document.content = payload.content
    if payload.status is not None: document.status = payload.status
    audit(db,request,user,'KNOWLEDGE_UPDATED','KNOWLEDGE',document.id,after={'version':document.version})
    if content_changed:
        replace_chunks(db, document)
    db.commit()
    return SuccessResponse(data=knowledge_out(document), request_id=request_id(request))


@router.delete("/admin/knowledge/documents/{document_id}", status_code=204)
def delete_knowledge(document_id: UUID, request: Request, if_match: str | None = Header(default=None, alias="If-Match"),
                     db: Session = Depends(get_db), user: User = Depends(require_user)) -> Response:
    require_csrf(request, db)
    manager(user)
    document = knowledge_or_404(db, str(document_id))
    expected = f'"v{document.version}"'
    if if_match is None:
        raise ApiError(428, "VERSION_REQUIRED", "删除资料需要 If-Match 版本")
    if if_match != expected:
        raise ApiError(409, "VERSION_CONFLICT", "资料已更新，请刷新后重试", {"current_version": document.version})
    version(db,document,match_version(if_match))
    document.status = "DELETED"
    audit(db,request,user,'KNOWLEDGE_DELETED','KNOWLEDGE',document.id)
    db.commit()
    return Response(status_code=204)
