// Deployed assets only. No uploads, arbitrary URLs or remote textures.
import {glbManifest} from './avatar-validation.js';
export async function mountAvatar(root,asset){
  if(asset.status!=='READY')return ()=>{};
  let renderer,scene,model,frame,observer,disposed=false;
  const fallback=root.querySelector('img');
  function release(){
    cancelAnimationFrame(frame);observer?.disconnect();
    const geometries=new Set(),materials=new Set(),textures=new Set();
    model?.traverse(object=>{if(object.geometry)geometries.add(object.geometry);for(const m of (Array.isArray(object.material)?object.material:[object.material]))if(m){materials.add(m);for(const v of Object.values(m))if(v?.isTexture)textures.add(v);}});
    for(const texture of textures){texture.dispose();texture.source?.data?.close?.();}
    for(const material of materials)material.dispose();
    for(const geometry of geometries)geometry.dispose();
    renderer?.dispose();renderer?.domElement.remove();model=null;renderer=null;
  }
  try{
    const THREE=await import('/vendor/three/three.module.js');
    const {GLTFLoader}=await import('/vendor/three/GLTFLoader.js');
    const response=await fetch(asset.content_url,{credentials:'same-origin'});if(!response.ok)throw new Error('3D资产读取失败');
    if(Number(response.headers.get('content-length'))>30*1048576)throw new Error('3D资产超过30MiB预算');
    const buffer=await response.arrayBuffer();glbManifest(buffer);
    const loading=new THREE.LoadingManager();loading.setURLModifier(url=>{if(!url.startsWith('blob:')&&!url.startsWith('data:'))throw new Error('禁止外部纹理加载');return url;});
    const gltf=await new GLTFLoader(loading).parseAsync(buffer,'');model=gltf.scene;scene=new THREE.Scene();scene.background=new THREE.Color('#0b213a');
    let triangles=0;
    model.traverse(object=>{
      if(object.isMesh&&object.visible)triangles+=(object.geometry.index?.count||object.geometry.attributes.position?.count||0)/3;
      for(const material of (Array.isArray(object.material)?object.material:[object.material])){
        if(!material)continue;
        for(const texture of Object.values(material)){
          if(!texture?.isTexture)continue;
          const image=texture.source?.data||texture.image;
          if(!image||!image.width||!image.height||Math.max(image.width,image.height)>2048)throw new Error('纹理尺寸无效或超过2048像素预算');
        }
      }
    });
    if(triangles>100000)throw new Error('可见三角形超过部署预算');
    const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3()),extent=Math.max(size.x,size.y,size.z);
    if(!Number.isFinite(extent)||extent<=0)throw new Error('3D资产没有有效可见尺寸');
    model.position.sub(center);scene.add(model);scene.add(new THREE.HemisphereLight(0xffffff,0x284765,3));
    const light=new THREE.DirectionalLight(0xffffff,4);light.position.set(2,3,4);scene.add(light);
    const camera=new THREE.PerspectiveCamera(35,1,.01,Math.max(1000,extent*10));camera.position.set(0,0,extent*2.2);
    renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));root.prepend(renderer.domElement);
    const resize=()=>{const width=Math.max(1,root.clientWidth-40),height=480;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();};
    resize();renderer.render(scene,camera);if(fallback)fallback.hidden=true;
    observer=new ResizeObserver(resize);observer.observe(root);
    function degrade(message){release();if(fallback)fallback.hidden=false;const label=root.querySelector('.muted');if(label)label.textContent='3D加载降级：'+message+'；文字交流仍可使用。';}
    renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();degrade('图形上下文丢失');},{once:true});
    function draw(){if(disposed||!renderer)return;try{if(!document.hidden)renderer.render(scene,camera);frame=requestAnimationFrame(draw);}catch{degrade('图形渲染失败');}}draw();
    root.querySelector('.muted').textContent='本地部署3D形象 · 文字交流独立运行';
  }catch(error){release();if(fallback)fallback.hidden=false;const label=root.querySelector('.muted');if(label)label.textContent='3D加载降级：'+error.message+'；文字交流仍可使用。';}
  return ()=>{disposed=true;release();};
}
