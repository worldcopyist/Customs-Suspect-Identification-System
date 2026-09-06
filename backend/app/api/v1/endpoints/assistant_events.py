import asyncio
import json
import time
from uuid import UUID
from fastapi import APIRouter,Depends,Header,Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import get_db,SessionLocal
from app.models import AssistantRequest,AuthSession
from app.services.security import require_user,session_from_request,validate_session,allowed_origin,ApiError
from app.services.llm import assistant_permission,sources_still_available
from app.api.v1.endpoints.assistant import request_out
router=APIRouter(tags=["assistant-stream"])

def checked(db,sid,id):
    session=db.get(AuthSession,sid)
    if not session:raise ApiError(401,"SESSION_REVOKED","登录已失效")
    user=validate_session(session,True);assistant_permission(user)
    row=db.get(AssistantRequest,id)
    if not row or row.owner_id!=user.id:raise ApiError(404,"NOT_FOUND","请求不存在")
    if not sources_still_available(db,row,user):raise ApiError(403,"SOURCE_ACCESS_REVOKED","来源权限已变化")
    return row
@router.get("/assistant/requests/{request_id}/events")
async def events(request_id:UUID,request:Request,last_event_id:str|None=Header(None),db:Session=Depends(get_db),user=Depends(require_user)):
    origin=request.headers.get("origin")
    if (origin and not allowed_origin(origin)) or request.headers.get("sec-fetch-site") in {"cross-site","same-site"}:raise ApiError(403,"ORIGIN_NOT_ALLOWED","必须同源订阅")
    id=str(request_id);sid=session_from_request(request,db).id;row=checked(db,sid,id)
    if not row.consented_at:raise ApiError(409,"REQUEST_NOT_CONFIRMED","需要先确认请求")
    stores=getattr(request.app.state,"assistant_events",{});store=stores.get(id);cursor=0
    if store and time.monotonic()-store["updated"]>300:store=None
    if row.state in {"SUCCEEDED","FAILED","CANCELLED","EXPIRED"} and not store:
        raise ApiError(409,"STREAM_RESUME_UNAVAILABLE","事件缓存不可用，请查询原请求最终状态")
    if last_event_id:
        prefix,_,seq=last_event_id.rpartition(":")
        if prefix!=id or not seq.isdigit() or not store or not store["events"] or time.monotonic()-store["updated"]>300 or not store["events"][0][0]-1<=int(seq)<=store["seq"]:raise ApiError(409,"STREAM_RESUME_UNAVAILABLE","无法连续重放，请查询原请求最终状态")
        cursor=int(seq)
    db.rollback()
    async def stream():
        nonlocal cursor
        terminal={"SUCCEEDED","FAILED","CANCELLED","EXPIRED"}
        yield 'event: status\ndata: '+json.dumps({"request_id":id,"reset_required":not bool(last_event_id),"stage":"RECEIVING"})+'\n\n'
        for attempt in range(180):
            if await request.is_disconnected():return
            try:
                with SessionLocal() as current:
                    row=checked(current,sid,id);snapshot=request_out(row)
                store=getattr(request.app.state,"assistant_events",{}).get(id)
                if store:
                    for seq,wire in list(store["events"]):
                        if seq>cursor:
                            with SessionLocal() as current:checked(current,sid,id)
                            yield wire;cursor=seq
                            if "\nevent: done\n" in wire:return
                if snapshot["state"] in terminal:
                    # REST snapshot is authoritative when an event cache is absent/incomplete.
                    if snapshot["state"]=="SUCCEEDED":yield 'event: answer.final\ndata: '+json.dumps({"request_id":id,**snapshot},ensure_ascii=False)+'\n\n'
                    else:yield 'event: error\ndata: '+json.dumps({"request_id":id,"code":snapshot["error_code"] or snapshot["state"],"message":"生成未完成，请重新准备并确认","discard_provisional":True})+'\n\n'
                    yield 'event: done\ndata: '+json.dumps({"request_id":id,"state":snapshot["state"],"billing_state":snapshot["billing_state"]})+'\n\n';return
            except ApiError as exc:
                yield 'event: error\ndata: '+json.dumps({"request_id":id,"code":exc.code,"message":exc.message,"discard_provisional":True})+'\n\n';return
            if attempt%15==0:yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"private,no-store","X-Accel-Buffering":"no"})
