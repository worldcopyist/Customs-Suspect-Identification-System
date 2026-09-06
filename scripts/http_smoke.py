"""Run only against the disposable smoke service; never the user's database."""
from uuid import uuid4
import httpx

BASE='http://127.0.0.1:8001'
PASSWORD='SmokeOnly!123456'
def write(c,path,data,key=None):
    csrf=c.get('/api/v1/auth/csrf').json()['data']['csrf_token']
    return c.post('/api/v1'+path,json=data,headers={'Origin':BASE,'X-CSRF-Token':csrf,'Idempotency-Key':key or str(uuid4())})
def run():
    with httpx.Client(base_url=BASE) as a,httpx.Client(base_url=BASE) as b:
        assert a.get('/api/v1/auth/csrf').status_code==200
        me=a.get('/api/v1/auth/me');assert me.status_code==401,me.text
        r=write(a,'/auth/login',{'username':'admin','password':'admin123'})
        assert r.status_code==200,r.text
        assert write(a,'/auth/password',{'current_password':'admin123','new_password':PASSWORD,'new_password_confirm':PASSWORD}).status_code==200
        assert write(a,'/auth/login',{'username':'admin','password':PASSWORD}).status_code==200
        r=write(b,'/auth/register',{'username':'smoke_user','display_name':'隔离测试用户','password':PASSWORD,'password_confirm':PASSWORD});assert r.status_code==201,r.text
        peer=r.json()['data']['id']
        assert write(b,'/auth/login',{'username':'smoke_user','password':PASSWORD}).status_code==200
        key=str(uuid4());body={'title':'真实HTTP联调群','member_ids':[peer]}
        r=write(a,'/admin/chat/groups',body,key);assert r.status_code==201,r.text
        gid=r.json()['data']['id'];assert write(a,'/admin/chat/groups',body,key).json()['data']['id']==gid
        r=write(b,f'/chat/conversations/{gid}/messages',{'client_message_id':str(uuid4()),'content':'真实HTTP联调成功 👍'});assert r.status_code==201,r.text
        assert a.get(f'/api/v1/chat/conversations/{gid}/messages').json()['data']['items'][0]['content']=='真实HTTP联调成功 👍'
        for path in ['/','/frontend.js','/ui/core.js','/ui/chat.js','/vendor/three/GLTFLoader.js','/api/v1/admin/dashboard/summary','/api/v1/admin/operations/logs']:
            assert a.get(path).status_code==200,path
        print('PASS: anonymous login, password lifecycle, register, group replay, peer message, static modules, dashboard and logs')
if __name__=='__main__':run()
