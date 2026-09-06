"""Public room, explicit presence and membership-scoped export."""
import csv
import io
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session
from app.db.session import get_db, SessionLocal
from app.models import AuthSession, User, Conversation, ConversationMember, ChatMessage
from app.schemas.auth import StrictModel
from app.services.security import require_user, require_csrf, require_manager, now, ApiError, session_from_request, validate_session
from app.services.business import allow, result, fields, paginate, interval, audit
from app.api.v1.endpoints.chat import active_member_or_404, to_conversation, to_message

router=APIRouter(tags=["community"])
PUBLIC_ID="00000000-0000-4000-8000-000000000001"
NOTICE="加入后可查看既有历史，你发送的内容也会对当前及未来加入的成员可见。"
class JoinIn(StrictModel):
    acknowledge_history_visibility:Literal[True]
class Empty(StrictModel):pass

def online_query(as_of):
    from app.core.config import get_settings
    return select(User).join(AuthSession,AuthSession.user_id==User.id).where(User.status=="ACTIVE",AuthSession.phase=="FULL",AuthSession.revoked_at.is_(None),AuthSession.expires_at>as_of,AuthSession.last_seen_at>as_of-timedelta(seconds=get_settings().session_idle_seconds),AuthSession.presence_at>as_of-timedelta(seconds=60)).distinct()
@router.post("/presence/heartbeat")
def heartbeat(payload:Empty,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    session=require_csrf(request,db);stamp=now();session.presence_at=stamp;db.commit()
    return result(request,{"as_of":stamp,"expires_at":stamp+timedelta(seconds=60),"heartbeat_interval_seconds":30})
@router.get("/chat/public-conversation")
def public(request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"chat.use");member=db.scalar(select(ConversationMember).where(ConversationMember.conversation_id==PUBLIC_ID,ConversationMember.user_id==user.id,ConversationMember.state=="ACTIVE"))
    return result(request,{"id":PUBLIC_ID,"title":"公共聊天室","type":"PUBLIC","joined":bool(member),"history_notice":NOTICE})
@router.post("/chat/public-conversation/join")
def join(payload:JoinIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"chat.use")
    member=db.scalar(select(ConversationMember).where(ConversationMember.conversation_id==PUBLIC_ID,ConversationMember.user_id==user.id))
    room=db.get(Conversation,PUBLIC_ID)
    if not member:member=ConversationMember(conversation_id=PUBLIC_ID,user_id=user.id,last_read_seq=room.last_seq);db.add(member)
    else:member.state="ACTIVE";member.removed_at=None;member.joined_at=now()
    db.flush();out=to_conversation(db,room,member,user);audit(db,request,user,"PUBLIC_JOINED","CONVERSATION",PUBLIC_ID);db.commit();return result(request,out)
@router.post("/chat/public-conversation/leave",status_code=204)
def leave(payload:Empty,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db);allow(user,"chat.use")
    member=db.scalar(select(ConversationMember).where(ConversationMember.conversation_id==PUBLIC_ID,ConversationMember.user_id==user.id))
    if member:member.state="REMOVED";member.removed_at=now()
    audit(db,request,user,"PUBLIC_LEFT","CONVERSATION",PUBLIC_ID);db.commit();return Response(status_code=204)
@router.get("/chat/conversations/{conversation_id}/presence")
def presence(conversation_id:UUID,request:Request,page:int=1,page_size:int=20,db:Session=Depends(get_db),user=Depends(require_user)):
    allow(user,"chat.use");active_member_or_404(db,str(conversation_id),user.id);stamp=now()
    stmt=online_query(stamp).join(ConversationMember,ConversationMember.user_id==User.id).where(ConversationMember.conversation_id==str(conversation_id),ConversationMember.state=="ACTIVE")
    rows=[x for x in db.scalars(stmt) if x.role!="USER" or "chat.use" in x.permissions]
    if page<1 or not 1<=page_size<=100:raise ApiError(422,"INVALID_FILTER","分页参数错误")
    return result(request,{"items":[{"user_id":x.id,"username":x.username,"display_name":x.display_name} for x in rows[(page-1)*page_size:page*page_size]],"total":len(rows),"page":page,"page_size":page_size,"as_of":stamp,"window_seconds":60})

class ExportIn(StrictModel):
    conversation_id:UUID|None=None
    sender_id:UUID|None=None
    q:str|None=Field(default=None,min_length=1,max_length=100)
    created_from:datetime
    created_to:datetime
    format:Literal["CSV"]="CSV"
def scoped_messages(db,user,start,end,cid=None,sender=None,q=None):
    require_manager(user);allow(user,"chat.use");start,end=interval(start,end)
    if cid:active_member_or_404(db,str(cid),user.id)
    stmt=select(ChatMessage).join(ConversationMember,ConversationMember.conversation_id==ChatMessage.conversation_id).where(ConversationMember.user_id==user.id,ConversationMember.state=="ACTIVE",ChatMessage.created_at>=start,ChatMessage.created_at<end)
    if cid:stmt=stmt.where(ChatMessage.conversation_id==str(cid))
    if sender:stmt=stmt.where(ChatMessage.sender_id==str(sender))
    if q:
        if len(q)>100:raise ApiError(422,"INVALID_FILTER","关键词最长100字符")
        stmt=stmt.where(ChatMessage.content.contains(q,autoescape=True))
    return stmt
@router.get("/admin/chat/messages")
def search(request:Request,created_from:datetime,created_to:datetime,conversation_id:UUID|None=None,sender_id:UUID|None=None,q:str|None=None,page:int=1,page_size:int=20,db:Session=Depends(get_db),user=Depends(require_user)):
    stmt=scoped_messages(db,user,created_from,created_to,conversation_id,sender_id,q)
    out=paginate(db,stmt.order_by(ChatMessage.created_at,ChatMessage.id),page,page_size,lambda x:to_message(x).model_dump(mode="json"))
    audit(db,request,user,"CHAT_SEARCH","CONVERSATION",str(conversation_id) if conversation_id else None,after={"created_from":created_from,"created_to":created_to,"sender_id":str(sender_id) if sender_id else None,"keyword_length":len(q or ""),"count":out["total"]});db.commit()
    return result(request,out)

def csv_cell(value):
    value=str(value or "")
    # Leading whitespace/control characters can mask spreadsheet formulas.
    if value.lstrip(" \t\r\n\x00\ufeff").startswith(("=","+","-","@")) or (value and ord(value[0])<32):value="'"+value
    return value
@router.post("/admin/chat/exports")
def export(payload:ExportIn,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    session=require_csrf(request,db)
    stmt=scoped_messages(db,user,payload.created_from,payload.created_to,payload.conversation_id,payload.sender_id,payload.q)
    rooms=dict(db.execute(select(ChatMessage.conversation_id,func.max(ChatMessage.seq)).where(ChatMessage.id.in_(stmt.with_only_columns(ChatMessage.id))).group_by(ChatMessage.conversation_id)).all())
    bounds=or_(*(and_(ChatMessage.conversation_id==cid,ChatMessage.seq<=seq) for cid,seq in rooms.items())) if rooms else ChatMessage.id.is_(None)
    stmt=stmt.where(bounds)
    count=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if count>10000:raise ApiError(422,"EXPORT_ROW_LIMIT","超过10000条，请缩小筛选范围")
    actor_id,session_id=user.id,session.id
    metadata={"conversation_ids":list(rooms),"created_from":payload.created_from.isoformat(),"created_to":payload.created_to.isoformat(),"count":count,"keyword_length":len(payload.q or "")}
    audit(db,request,user,"CHAT_EXPORT_STARTED","EXPORT",None,after=metadata);db.commit()
    def stream():
        sent=0;complete=False
        try:
            buf=io.StringIO();writer=csv.writer(buf);writer.writerow(["conversation_id","message_id","sender_id","sender_display_name","message_type","content","created_at"])
            yield "\ufeff"+buf.getvalue()
            while sent<count:
                with SessionLocal() as current_db:
                    current=current_db.get(AuthSession,session_id)
                    if not current:raise ApiError(401,"SESSION_REVOKED","会话已失效")
                    actor=validate_session(current,require_full=True);require_manager(actor);allow(actor,"chat.use")
                    for cid in rooms:active_member_or_404(current_db,cid,actor_id)
                    chunk=list(current_db.scalars(stmt.order_by(ChatMessage.created_at,ChatMessage.id).offset(sent).limit(200)))
                    buf=io.StringIO();writer=csv.writer(buf)
                    for m in chunk:writer.writerow([csv_cell(x) for x in (m.conversation_id,m.id,m.sender_id,m.sender_display_name,"TEXT",m.content,m.created_at.isoformat())])
                if not chunk:break
                sent+=len(chunk);yield buf.getvalue()
            complete=sent==count
        finally:
            with SessionLocal() as current_db:
                actor=current_db.get(User,actor_id)
                audit(current_db,request,actor,"CHAT_EXPORT_COMPLETED" if complete else "CHAT_EXPORT_INTERRUPTED","EXPORT",None,after={**metadata,"sent_count":sent},outcome="SUCCESS" if complete else "FAILED");current_db.commit()
    return StreamingResponse(stream(),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="chat-export.csv"',"Cache-Control":"private,no-store"})
