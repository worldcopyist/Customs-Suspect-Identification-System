"""Real local-model smoke with synthetic blank images in the disposable service."""
import io,time
from uuid import uuid4
import httpx
from PIL import Image
from http_smoke import BASE,PASSWORD,write
def main():
    with httpx.Client(base_url=BASE,timeout=60) as c:
        assert write(c,'/auth/login',{'username':'smoke_user','password':PASSWORD}).status_code==200
        image=io.BytesIO();Image.new('RGB',(640,480),'white').save(image,'PNG');ids=[]
        for _ in range(2):
            token=c.get('/api/v1/auth/csrf').json()['data']['csrf_token']
            r=c.post('/api/v1/media',files={'file':('synthetic-blank.png',image.getvalue(),'image/png')},data={'purpose':'DETECTION_IMAGE'},headers={'Origin':BASE,'X-CSRF-Token':token,'Idempotency-Key':str(uuid4())})
            assert r.status_code==201,r.text
            ids.append(r.json()['data']['id'])
        r=write(c,'/detections/batches',{'media_ids':ids});assert r.status_code==202,r.text
        bid=r.json()['data']['id'];deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            r=c.get('/api/v1/detections/batches/'+bid);assert r.status_code==200,r.text
            data=r.json()['data']
            if data['state']!='RUNNING':break
            time.sleep(.5)
        assert data['state']=='COMPLETED' and data['succeeded_count']==2,data
        for item in data['items']:
            assert item['rendered_media_id'] and item['rendered_media_id']!=item['source_media_id'],item
            for id in [item['rendered_media_id'],item['source_media_id']]:assert c.get('/api/v1/media/'+id+'/content').status_code==200
        print('PASS: real YOLO subprocess, two-image scheduler, completed counts, separate original and watermarked media')
if __name__=='__main__':main()
