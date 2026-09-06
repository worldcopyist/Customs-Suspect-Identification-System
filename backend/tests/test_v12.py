from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.main import create_app
from app.db.session import SessionLocal
from app.models import User,Media,Detection,DetectionBox,AuthSession
from app.models.extension import DetectionBatch
from app.services.security import now
from app.core.config import get_settings

ORIGIN='http://127.0.0.1:8000'
PASSWORD='Correct!123456'
def test_anonymous_csrf_cookie_does_not_force_password_change():
    with TestClient(create_app(),base_url=ORIGIN) as c:
        assert c.get('/api/v1/auth/csrf').status_code==200
        r=c.get('/api/v1/auth/me')
        assert r.status_code==401 and r.json()['error']['code']=='UNAUTHENTICATED'
def send(c,path,payload=None,method='POST',key=None,**headers):
    token=c.get('/api/v1/auth/csrf').json()['data']['csrf_token']
    return c.request(method,'/api/v1'+path,json=payload,headers={'Origin':ORIGIN,'X-CSRF-Token':token,'Idempotency-Key':key or str(uuid4()),**headers})
def login(c,name='admin',password=PASSWORD):
    r=send(c,'/auth/login',{'username':name,'password':password});assert r.status_code==200,r.text
    return r.json()['data']['user']
@pytest.fixture
def clients():
    app=create_app()
    with TestClient(app,base_url=ORIGIN) as admin:
        send(admin,'/auth/login',{'username':'admin','password':'admin123'})
        assert send(admin,'/auth/password',{'current_password':'admin123','new_password':PASSWORD,'new_password_confirm':PASSWORD}).status_code==200
        root=login(admin)
        bob=TestClient(app,base_url=ORIGIN)
        assert send(bob,'/auth/register',{'username':'bob','display_name':'Bob','password':PASSWORD,'password_confirm':PASSWORD}).status_code==201
        user=login(bob,'bob')
        yield admin,bob,root,user,app
        bob.close()

def test_public_group_private_and_export_acl(clients):
    a,b,root,user,_=clients
    room=a.get('/api/v1/chat/public-conversation').json()['data'];rid=room['id']
    assert not room['joined']
    assert a.get(f'/api/v1/chat/conversations/{rid}/messages').status_code==404
    assert send(a,'/chat/public-conversation/join',{}).status_code==422
    assert send(a,'/chat/public-conversation/join',{'acknowledge_history_visibility':True}).status_code==200
    mid=str(uuid4());body={'client_message_id':mid,'content':'=1+1'}
    assert send(a,f'/chat/conversations/{rid}/messages',body).status_code==201
    assert send(b,'/chat/public-conversation/join',{'acknowledge_history_visibility':True}).status_code==200
    assert b.get(f'/api/v1/chat/conversations/{rid}/messages').json()['data']['items'][0]['content']=='=1+1'
    dates={'created_from':(now()-timedelta(days=1)).isoformat(),'created_to':(now()+timedelta(seconds=1)).isoformat(),'conversation_id':rid}
    exported=send(a,'/admin/chat/exports',dates);assert exported.status_code==200,exported.text
    assert "'=1+1" in exported.text
    assert send(b,'/admin/chat/exports',dates).status_code==403
    assert send(a,'/chat/public-conversation/leave',{}).status_code==204
    assert send(a,'/admin/chat/exports',dates).status_code==404
    key=str(uuid4());group={'title':'集成测试群','member_ids':[user['id']]}
    first=send(a,'/admin/chat/groups',group,key=key);assert first.status_code==201,first.text
    second=send(a,'/admin/chat/groups',group,key=key);assert second.json()['data']['id']==first.json()['data']['id']
    gid=first.json()['data']['id']
    assert any(x['id']==gid for x in b.get('/api/v1/chat/conversations').json()['data']['items'])
    direct=send(a,'/chat/direct-conversations',{'peer_user_id':user['id']});assert direct.status_code==201,direct.text
    did=direct.json()['data']['id']
    msg=send(b,f'/chat/conversations/{did}/messages',{'client_message_id':str(uuid4()),'content':'私聊互通 👍'})
    assert msg.status_code==201,msg.text
    assert a.get(f'/api/v1/chat/conversations/{did}/messages').json()['data']['items'][0]['content']=='私聊互通 👍'

def test_person_cas_review_link_and_soft_delete_metrics(clients):
    a,b,root,user,_=clients
    p=send(a,'/persons',{'person_code':'P001','name':'人工维护档案'});assert p.status_code==201,p.text
    p=p.json()['data'];pid=p['id']
    assert send(b,'/persons',{'person_code':'P002','name':'越权'}).status_code==403
    patch={'name':'新名称','expected_version':p['version']}
    assert send(a,'/persons/'+pid,patch,'PATCH').status_code==200
    assert send(a,'/persons/'+pid,patch,'PATCH').status_code==409
    with SessionLocal.begin() as db:
        row=Detection(owner_id=user['id'],source='IMAGE',state='SUCCEEDED',review_status='PENDING',finished_at=now()-timedelta(seconds=1))
        row.boxes=[DetectionBox(box_index=0,class_id=0,class_name='sus',confidence=.6,bbox=[1,2,30,40])];db.add(row);db.flush();did=row.id;bid=row.boxes[0].id
    metrics=a.get('/api/v1/admin/dashboard/summary').json()['data'];assert metrics['total_hit_record_count']==1 and metrics['detected_box_count']==1
    review=send(b,f'/detections/{did}/review',{'review_status':'FALSE_POSITIVE','comment':'人工复核','expected_version':1},'PUT');assert review.status_code==200,review.text
    linked=send(a,f'/detections/{did}/boxes/{bid}/person-link',{'person_id':pid,'expected_version':2,'comment':'人工匹配'},'PUT');assert linked.status_code==200,linked.text
    assert linked.json()['data']['box']['person_link']['name_snapshot']=='新名称'
    assert a.get(f'/api/v1/detections/{did}/history').json()['data']['total']==2
    assert a.get('/api/v1/admin/dashboard/summary').json()['data']['false_positive_record_count']==1
    assert send(a,f'/detections/{did}',method='DELETE',**{'If-Match':'"v3"'}).status_code==204
    assert b.get(f'/api/v1/detections/{did}').status_code==404
    assert a.get('/api/v1/admin/dashboard/summary').json()['data']['total_hit_record_count']==0

def test_chat_history_cursors_and_dissolved_group(clients):
    from app.models import Conversation,ChatMessage
    a,b,root,user,_=clients
    group=send(a,'/admin/chat/groups',{'title':'分页测试群','member_ids':[user['id']]}).json()['data']
    gid=group['id']
    with SessionLocal.begin() as db:
        db.get(Conversation,gid).last_seq=205
        for seq in range(1,206):
            db.add(ChatMessage(conversation_id=gid,sender_id=root['id'],sender_display_name='测试',seq=seq,client_message_id=str(uuid4()),content=f'分页消息 {seq}'))
    path=f'/api/v1/chat/conversations/{gid}/messages'
    latest=b.get(path+'?limit=100').json()['data']
    assert latest['has_more'] and [x['seq'] for x in latest['items']]==list(map(str,range(106,206)))
    older=b.get(path+'?limit=100&before_seq='+latest['next_before_seq']).json()['data']
    assert older['has_more'] and older['items'][0]['seq']=='6'
    first=b.get(path+'?limit=100&before_seq='+older['next_before_seq']).json()['data']
    assert not first['has_more'] and len(first['items'])==5
    assert b.get(path+'?limit=100&after_seq=205').json()['data']['items']==[]
    assert send(a,f'/admin/chat/groups/{gid}/dissolve',{'expected_version':group['version']}).status_code==200
    assert b.get(f'/api/v1/chat/conversations/{gid}').json()['data']['state']=='DISSOLVED'
    assert send(b,f'/chat/conversations/{gid}/messages',{'client_message_id':str(uuid4()),'content':'不能发送'}).status_code==409
    assert b.get(path).status_code==200

def test_log_request_id_and_event_filters(clients):
    a,b,root,user,_=clients
    response=send(a,'/auth/me',{'display_name':'请求编号测试','expected_version':root['version']},'PATCH')
    assert response.status_code==200,response.text
    trace=response.json()['request_id']
    ops=a.get('/api/v1/admin/operations/logs',params={'request_id':trace}).json()['data']
    assert ops['items'] and all(row['request_id']==trace for row in ops['items'])
    event=ops['items'][0]['event_code']
    assert a.get('/api/v1/admin/operations/logs',params={'request_id':trace,'event_code':event}).json()['data']['total']>0
    assert a.get('/api/v1/admin/operations/logs',params={'request_id':trace,'event_code':'NOT_AN_EVENT'}).json()['data']['total']==0
    audits=a.get('/api/v1/admin/audit-logs',params={'request_id':trace}).json()['data']
    assert audits['items'] and all(row['request_id']==trace for row in audits['items'])
    assert b.get('/api/v1/admin/operations/logs',params={'request_id':trace}).status_code==403

def test_batch_atomic_acceptance_cancellation_and_history(clients):
    a,b,root,user,app=clients
    # Stop real scheduler: this test asserts acceptance, not mocked model quality.
    coordinator=app.state.inference_coordinator
    app.state.inference_coordinator=SimpleNamespace(available=True,settings=get_settings())
    try:
        ids=[]
        with SessionLocal.begin() as db:
            for i in range(2):
                m=Media(owner_id=user['id'],purpose='DETECTION_IMAGE',mime_type='image/png',byte_size=100,upload_byte_size=100,width=20,height=20,sha256='0'*64,storage_key=str(uuid4()),expires_at=now()+timedelta(hours=1));db.add(m);db.flush();ids.append(m.id)
        invalid=send(b,'/detections/batches',{'media_ids':[ids[0],str(uuid4())]});assert invalid.status_code==422,invalid.text
        with SessionLocal() as db:assert db.get(Media,ids[0]).state=='STAGED'
        accepted=send(b,'/detections/batches',{'media_ids':ids});assert accepted.status_code==202,accepted.text
        batch=accepted.json()['data'];assert batch['total_count']==2 and batch['processed_count']==0
        assert send(b,'/detections/batches',{'media_ids':ids}).status_code==409
        cancelled=send(b,f"/detections/batches/{batch['id']}/cancel",{});assert cancelled.status_code==200,cancelled.text
        data=cancelled.json()['data'];assert data['cancelled_count']==2 and data['state']=='CANCELLED'
        assert send(a,'/detections/'+data['items'][0]['id'],method='DELETE',**{'If-Match':'"v1"'}).status_code==204
        final=b.get('/api/v1/detections/batches/'+batch['id']).json()['data'];assert final['cancelled_count']==2 and final['items'][0]['hidden']
    finally:app.state.inference_coordinator=coordinator

def test_background_presence_does_not_extend_idle_session(clients):
    a,b,root,user,_=clients
    with SessionLocal.begin() as db:
        s=db.scalar(select(AuthSession).where(AuthSession.user_id==user['id'],AuthSession.revoked_at.is_(None)));s.last_seen_at=now()-timedelta(minutes=29);old=s.last_seen_at.replace(tzinfo=None);sid=s.id
    assert send(b,'/presence/heartbeat',{}).status_code==200
    assert b.get('/api/v1/chat/users',headers={'X-Background-Request':'true'}).status_code==200
    with SessionLocal.begin() as db:
        s=db.get(AuthSession,sid);assert s.last_seen_at.replace(tzinfo=None)==old;s.last_seen_at=now()-timedelta(minutes=31)
    assert b.get('/api/v1/auth/me').status_code==401
    # Expired csrf session is replaced; legitimate re-login must not be stuck.
    login(b,'bob')
    denied=send(b,'/auth/login',{'username':'bob','password':PASSWORD,'portal':'ADMIN'});assert denied.status_code==403

@pytest.mark.parametrize('path',['/.env','/backend/data/customs_training.db','/backend/logs/app.log','/app.js','/system/config','/api/v1/digital-human/model'])
def test_private_files_and_removed_routes_not_served(clients,path):
    a,*_=clients
    assert a.get(path).status_code in {404,405}

def test_maintenance_views_do_not_include_passwords(clients):
    a,b,root,user,_=clients
    send(b,'/auth/login',{'username':'bob','password':'SecretMustNotBeLogged!'})
    for path in ['/admin/operations/logs','/admin/audit-logs']:
        response=a.get('/api/v1'+path);assert response.status_code==200,response.text
        assert PASSWORD not in response.text and 'SecretMustNotBeLogged!' not in response.text
    assert b.get('/api/v1/admin/operations/logs').status_code==403

def test_camera_generation_and_owner_boundaries(clients):
    a,b,root,user,_=clients
    start=send(b,'/camera/sessions',{'capture_interval_ms':500});assert start.status_code==201,start.text
    sid=start.json()['data']['id']
    assert send(a,f'/camera/sessions/{sid}/pause',{'generation':1}).status_code==404
    paused=send(b,f'/camera/sessions/{sid}/pause',{'generation':1});assert paused.status_code==200,paused.text
    assert paused.json()['data']['generation']==2 and paused.json()['data']['state']=='PAUSED'
    assert send(b,f'/camera/sessions/{sid}/snapshots',{'generation':2,'frame_id':str(uuid4())}).status_code==409
    assert send(b,f'/camera/sessions/{sid}/resume',{'generation':1}).status_code==409
    resumed=send(b,f'/camera/sessions/{sid}/resume',{'generation':2,'capture_interval_ms':1000});assert resumed.status_code==200,resumed.text
    assert resumed.json()['data']['capture_interval_ms']==1000
    assert send(b,f'/camera/sessions/{sid}/stop',{}).status_code==200
    assert send(b,f'/camera/sessions/{sid}/heartbeat',{}).status_code==410

def test_agent_frozen_prepare_and_single_cloud_dispatch(clients,monkeypatch):
    from app.models import ProviderConfig,AssistantRequest
    from app.models.extension import AgentProfile
    from app.services.llm import encrypt_secret,secret_fingerprint,validation_fingerprint
    a,b,root,user,app=clients
    calls=[]
    async def provider(config,messages,on_delta=None):
        calls.append((config.temperature,messages))
        if on_delta:await on_delta('离线适配器测试输出')
        return {'text':'离线适配器测试输出','usage':{'input_tokens':1,'output_tokens':1},'finish_reason':'stop','request_id':'test-only'}
    monkeypatch.setattr('app.services.llm.provider_generate',provider)
    with SessionLocal.begin() as db:
        p=ProviderConfig(provider='DEEPSEEK',name='隔离适配器',base_url='https://api.deepseek.com',model='test',api_key_encrypted=encrypt_secret('not-real'),api_key_fingerprint=secret_fingerprint('not-real'),enabled=True,capabilities={'supports_stream':True,'supports_temperature':True,'temperature_min':0,'temperature_max':2})
        db.add(p);db.flush();p.validation_fingerprint=validation_fingerprint(p)
        agent=AgentProfile(name='测试角色',business_prompt='提供课程帮助',temperature=.6,provider_config_id=p.id,status='ACTIVE');db.add(agent);db.flush();agent_id=agent.id
    conv=send(b,'/assistant/conversations',{'title':'隔离测试'}).json()['data']['id']
    payload={'conversation_id':conv,'agent_profile_id':agent_id,'question':'请介绍课程','mode':'GENERAL'}
    first=send(b,'/assistant/requests/prepare',payload);assert first.status_code==201,first.text
    first=first.json()['data'];assert not calls
    assert first['outbound_preview']['configuration']['temperature']==.6
    assert send(a,'/admin/assistant/agents/'+agent_id,{'name':'角色新版本','expected_version':1},'PATCH').status_code==200
    assert send(b,'/assistant/requests/'+first['id']+'/confirm',{'consent':True,'payload_hash':first['payload_hash']}).status_code==412
    prepared=send(b,'/assistant/requests/prepare',payload).json()['data'];rid=prepared['id']
    assert send(b,f'/assistant/requests/{rid}/confirm',{'consent':True,'payload_hash':prepared['payload_hash']}).status_code==202
    assert send(b,f'/assistant/requests/{rid}/confirm',{'consent':True,'payload_hash':prepared['payload_hash']}).status_code==202
    assert len(calls)==1 and calls[0][0]==.6
    completed=b.get('/api/v1/assistant/requests/'+rid);assert completed.json()['data']['state']=='SUCCEEDED',completed.text
    events=b.get('/api/v1/assistant/requests/'+rid+'/events');assert events.status_code==200,events.text
    assert 'event: answer.delta' in events.text and 'event: answer.final' in events.text and events.text.count('event: done')==1
    assert a.get('/api/v1/assistant/requests/'+rid).status_code==404
    assert b.get('/api/v1/assistant/requests/'+rid+'/events',headers={'Last-Event-ID':str(uuid4())+':1'}).status_code==409
    assert len(calls)==1
    app.state.assistant_events.clear()
    assert b.get('/api/v1/assistant/requests/'+rid+'/events').status_code==409

def test_browser_diagnostics_only_accepts_safe_schema(clients):
    a,b,*_=clients
    assert send(b,'/client-diagnostics',{'event_code':'SCRIPT_ERROR','module':'chat'}).status_code==202
    assert send(b,'/client-diagnostics',{'event_code':'SCRIPT_ERROR','message':'secret'}).status_code==422
    data=a.get('/api/v1/admin/operations/logs?module=browser').json()['data'];assert data['total']==1

@pytest.mark.parametrize('stream,low,high,expected',[(False,None,None,[None]),(True,0,2,[0,2]),(False,.7,.7,[.7])])
def test_provider_capability_probes_are_explicit_and_idempotent(clients,monkeypatch,stream,low,high,expected):
    a,b,root,user,_=clients
    calls=[]
    async def generate(config,messages):
        calls.append((config.capabilities['supports_stream'],config.temperature))
        return {'text':'连接测试成功。','finish_reason':'stop','usage':{'input_tokens':4,'output_tokens':3}}
    monkeypatch.setattr('app.api.v1.endpoints.operations.provider_generate',generate)
    made=send(a,'/admin/llm/providers',{'provider':'DEEPSEEK','name':'协议测试','base_url':'https://api.deepseek.com','model':'test-only','api_key':'fake-test-only'})
    assert made.status_code==201,made.text
    pid=made.json()['data']['id']
    payload={'consent_to_test':True,'expected_version':1,'test_stream':stream,'temperature_min':low,'temperature_max':high}
    key=str(uuid4())
    response=send(a,f'/admin/llm/providers/{pid}/test',payload,key=key)
    assert response.status_code==200,response.text
    assert calls==[(stream,t) for t in expected]
    assert response.json()['data']['test_call_count']==len(expected)
    again=send(a,f'/admin/llm/providers/{pid}/test',payload,key=key)
    assert again.status_code==200 and len(calls)==len(expected)
    current=a.get('/api/v1/admin/llm/providers').json()['data']['items'][0]
    assert current['is_validated'] and not current['enabled']
    assert current['capabilities']['temperature_min']==low
    assert current['capabilities']['supports_temperature']==(low is not None)
    assert send(b,f'/admin/llm/providers/{pid}/test',payload).status_code==403

def test_failed_capability_probe_does_not_retry_or_certify(clients,monkeypatch):
    from app.services.security import ApiError
    a,*_=clients
    calls=[]
    async def fail(config,messages):
        calls.append(config.temperature)
        raise ApiError(502,'PROVIDER_RESPONSE_INVALID','测试拒绝')
    monkeypatch.setattr('app.api.v1.endpoints.operations.provider_generate',fail)
    pid=send(a,'/admin/llm/providers',{'provider':'DEEPSEEK','name':'失败测试','base_url':'https://api.deepseek.com','model':'test-only','api_key':'fake-test-only'}).json()['data']['id']
    key=str(uuid4());payload={'consent_to_test':True,'expected_version':1,'test_stream':True,'temperature_min':0,'temperature_max':2}
    assert send(a,f'/admin/llm/providers/{pid}/test',payload,key=key).status_code==502
    again=send(a,f'/admin/llm/providers/{pid}/test',payload,key=key)
    assert again.status_code==409 and again.json()['error']['code']=='OUTCOME_UNKNOWN'
    assert calls==[0]
    current=a.get('/api/v1/admin/llm/providers').json()['data']['items'][0]
    assert not current['is_validated'] and not current['enabled']

def test_restart_preserves_unstarted_jobs_without_reexecuting_running_jobs():
    from app.core.lifecycle import initialize_database
    initialize_database()
    timestamp=now().isoformat()
    with SessionLocal.begin() as db:
        owner=db.scalar(select(User).where(User.username=='admin'))
        queued=Detection(owner_id=owner.id,source='IMAGE',state='QUEUED',config_snapshot={'queued_at':timestamp})
        running=Detection(owner_id=owner.id,source='IMAGE',state='RUNNING',config_snapshot={'queued_at':timestamp})
        db.add_all([queued,running]);db.flush();qid,rid=queued.id,running.id
    initialize_database()
    with SessionLocal() as db:
        assert db.get(Detection,qid).state=='PENDING'
        assert db.get(Detection,qid).config_snapshot['queued_at']==timestamp
        assert db.get(Detection,rid).state=='FAILED'
        assert db.get(Detection,rid).error_code=='PROCESS_RESTARTED'

def business_agent(root):
    from app.models import ProviderConfig
    from app.models.extension import AgentProfile
    from app.services.llm import encrypt_secret,secret_fingerprint,validation_fingerprint
    with SessionLocal.begin() as db:
        provider=ProviderConfig(provider='DEEPSEEK',name='离线业务验证',base_url='https://api.deepseek.com',model='offline-only',api_key_encrypted=encrypt_secret('fake-offline-key'),api_key_fingerprint=secret_fingerprint('fake-offline-key'),enabled=True,capabilities={'supports_stream':True,'supports_temperature':True,'temperature_min':0,'temperature_max':2})
        db.add(provider);db.flush();provider.validation_fingerprint=validation_fingerprint(provider)
        agent=AgentProfile(name='业务测试角色',business_prompt='帮助实训',temperature=.7,provider_config_id=provider.id,status='ACTIVE',created_by=root['id'])
        db.add(agent);db.flush();return agent.id

@pytest.mark.parametrize('mode',['SUMMARY','REPORT'])
def test_report_facts_are_server_owned_and_citations_recheck_access(clients,monkeypatch,mode):
    import json
    a,b,root,user,_=clients
    agent_id=business_agent(root)
    with SessionLocal.begin() as db:
        row=Detection(owner_id=user['id'],source='IMAGE',state='SUCCEEDED',review_status='FALSE_POSITIVE',finished_at=now(),model_id='local-model',model_sha256='a'*64,config_snapshot={'threshold':.25})
        row.boxes=[DetectionBox(box_index=0,class_id=0,class_name='sus',confidence=.6,bbox=[1,2,3,4],person_link={'person_code_snapshot':'P001','name_snapshot':'NEVER_SEND_THIS_NAME'})]
        db.add(row);db.flush();did=row.id
    calls=[]
    async def generate(config,messages,on_delta=None):
        calls.append(messages)
        if on_delta:await on_delta('不应提前显示的正文')
        return {'text':json.dumps({'pending_checks':[{'code':'CHECK_MANUAL_LINKS','citations':['D1']}]}),'finish_reason':'stop','request_id':'offline','usage':None}
    monkeypatch.setattr('app.services.llm.provider_generate',generate)
    conv=send(b,'/assistant/conversations',{'title':'业务报告测试'}).json()['data']['id']
    prepare_key=str(uuid4());prepare_payload={'conversation_id':conv,'agent_profile_id':agent_id,'mode':mode,'question':'整理待核对信息','detection_ids':[did]}
    prepared=send(b,'/assistant/requests/prepare',prepare_payload,key=prepare_key)
    assert prepared.status_code==201,prepared.text
    prepared=prepared.json()['data'];rid=prepared['id']
    assert 'NEVER_SEND_THIS_NAME' not in json.dumps(prepared['outbound_preview'])
    assert 'P001' in prepared['outbound_preview']['evidence_text']
    assert 'FALSE_POSITIVE' in prepared['outbound_preview']['evidence_text']
    assert not calls
    assert send(b,f'/assistant/requests/{rid}/confirm',{'consent':True,'payload_hash':prepared['payload_hash']}).status_code==202
    result=b.get(f'/api/v1/assistant/requests/{rid}').json()['data']
    assert result['state']=='SUCCEEDED',result
    assert '候选框 1 个' in result['answer'] and 'P001' in result['answer'] and '人工关联' in result['answer']
    assert 'AI生成，需人工核验' in result['answer']
    stream=b.get(f'/api/v1/assistant/requests/{rid}/events').text
    assert 'event: answer.delta' not in stream and '不应提前显示的正文' not in stream
    citation=b.get(f'/api/v1/assistant/requests/{rid}/citations/D1');assert citation.status_code==200,citation.text
    assert citation.json()['data']['facts']['box_count']==1
    assert a.get(f'/api/v1/assistant/requests/{rid}/citations/D1').status_code==404
    assert send(a,f'/detections/{did}',method='DELETE',**{'If-Match':'"v1"'}).status_code==204
    assert b.get(f'/api/v1/assistant/requests/{rid}/citations/D1').status_code==403
    assert b.get(f'/api/v1/assistant/requests/{rid}').status_code==403
    assert send(b,'/assistant/requests/prepare',prepare_payload,key=prepare_key).status_code==403
    history=b.get(f'/api/v1/assistant/conversations/{conv}/messages').json()['data']['items']
    assert history and all(x['hidden'] and 'content' not in x for x in history)

def test_knowledge_points_require_sources_and_changed_document_hides_answer(clients,monkeypatch):
    import json
    a,b,root,user,_=clients
    agent_id=business_agent(root)
    doc=send(a,'/admin/knowledge/documents',{'title':'安全复核','content':'安全复核需要人工核验，不能由候选框确认人员身份。','status':'ACTIVE'}).json()['data']
    async def generate(config,messages,on_delta=None):
        return {'text':json.dumps({'points':[{'text':'安全复核需要人工核验。','citations':['K1']}],'scope_note':'仅适用于本次实训资料。'},ensure_ascii=False),'finish_reason':'stop','request_id':'offline','usage':None}
    monkeypatch.setattr('app.services.llm.provider_generate',generate)
    conv=send(b,'/assistant/conversations',{'title':'资料测试'}).json()['data']['id']
    prepared=send(b,'/assistant/requests/prepare',{'conversation_id':conv,'agent_profile_id':agent_id,'mode':'KNOWLEDGE','question':'安全复核'}).json()['data'];rid=prepared['id']
    assert send(b,f'/assistant/requests/{rid}/confirm',{'consent':True,'payload_hash':prepared['payload_hash']}).status_code==202
    result=b.get(f'/api/v1/assistant/requests/{rid}').json()['data'];assert result['state']=='SUCCEEDED',result
    assert result['citations'][0]['title']=='安全复核'
    assert b.get(f'/api/v1/assistant/requests/{rid}/citations/K1').json()['data']['content']==doc['content']
    assert b.get(f'/api/v1/assistant/requests/{rid}/citations/K99').status_code==404
    assert send(a,'/admin/knowledge/documents/'+doc['id'],{'expected_version':doc['version'],'status':'INACTIVE'},'PATCH').status_code==200
    assert b.get(f'/api/v1/assistant/requests/{rid}/citations/K1').status_code==403

@pytest.mark.parametrize('text',[
    '随意的一段非结构化报告',
    '{"pending_checks":[{"code":"VERIFY_SOURCE","citations":["D99"]}]}',
    '{"pending_checks":[{"code":"VERIFY_SOURCE","citations":["D1"]}],"box_count":999}',
    '{"pending_checks":[{"code":"ARREST_PERSON","citations":["D1"]}]}',
])
def test_business_output_rejects_fabricated_fields_and_unknown_citations(text):
    from app.services.llm import validate_answer
    from app.services.security import ApiError
    request=SimpleNamespace(mode='REPORT',source_refs=[{'label':'D1'}],outbound_payload={})
    with pytest.raises(ApiError) as raised:validate_answer(text,request)
    assert raised.value.code=='OUTPUT_VALIDATION_FAILED'

@pytest.mark.asyncio
@pytest.mark.parametrize('stream',[False,True])
async def test_provider_tool_calls_are_rejected_before_display(monkeypatch,stream):
    import json,httpx
    from app.services.llm import provider_generate,encrypt_secret
    from app.services.security import ApiError
    part={'content':'不能显示的正文','tool_calls':[{'type':'function','function':{'name':'change_record','arguments':'{}'}}]}
    class Response:
        status_code=200
        headers={}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def aiter_lines(self):
            yield 'data: '+json.dumps({'choices':[{'delta':part,'finish_reason':None}]})
            yield 'data: [DONE]'
    class Client:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,*args,**kwargs):return httpx.Response(200,json={'choices':[{'message':part,'finish_reason':'tool_calls'}]})
        def stream(self,*args,**kwargs):return Response()
    monkeypatch.setattr('app.services.llm.verify_public_dns',lambda _:None)
    monkeypatch.setattr('httpx.AsyncClient',Client)
    config=SimpleNamespace(provider='DEEPSEEK',model='offline',base_url='https://api.deepseek.com',api_key_encrypted=encrypt_secret('fake-key'),temperature=None,timeout_seconds=60,max_output_tokens=256,capabilities={'supports_stream':stream})
    visible=[]
    async def delta(text):visible.append(text)
    with pytest.raises(ApiError) as raised:await provider_generate(config,[],delta)
    assert raised.value.code=='PROVIDER_RESPONSE_INVALID' and not visible
