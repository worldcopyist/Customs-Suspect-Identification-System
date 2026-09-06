"""Diagnostic local inference invocation, no business database or external calls."""
from io import BytesIO
from PIL import Image
from app.workers.inference import YoloInferenceWorker
def main():
    image=BytesIO();Image.new('RGB',(640,480),'white').save(image,'JPEG')
    worker=YoloInferenceWorker()
    try:
        result=worker.predict(image.getvalue());print('real worker completed',result.image_width,result.image_height,len(result.boxes))
    finally:worker.close()
if __name__=='__main__':main()
