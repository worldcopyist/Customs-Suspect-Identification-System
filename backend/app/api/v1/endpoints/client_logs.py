"""Small authenticated browser diagnostics: never accept page text or secrets."""
from typing import Literal
from fastapi import APIRouter,Depends,Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.extension import OperationLog
from app.schemas.auth import StrictModel
from app.services.security import require_user,require_csrf
from app.services.business import result
router=APIRouter(tags=['client-diagnostics'])
class ClientEvent(StrictModel):
    event_code:Literal['SCRIPT_ERROR','UNHANDLED_REJECTION']
    module:Literal['authentication','detection','chat','assistant','administration','application']='application'
@router.post('/client-diagnostics',status_code=202)
def record(payload:ClientEvent,request:Request,db:Session=Depends(get_db),user=Depends(require_user)):
    require_csrf(request,db)
    db.add(OperationLog(level='ERROR',module='browser',event_code=payload.event_code,request_id=request.state.request_id,safe_context={'module':payload.module,'actor_id':user.id}))
    db.commit()
    return result(request,{'recorded':True})
