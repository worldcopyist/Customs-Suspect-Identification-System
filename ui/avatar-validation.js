export function glbManifest(buffer){
  if(buffer.byteLength>30*1048576)throw new Error('3D资产超过30MiB预算');
  if(buffer.byteLength<20)throw new Error('GLB文件不完整');
  const view=new DataView(buffer);
  if(view.getUint32(0,true)!==0x46546c67||view.getUint32(4,true)!==2||view.getUint32(8,true)!==buffer.byteLength)throw new Error('需要合法GLB 2.0资源');
  const length=view.getUint32(12,true);
  if(length%4||20+length>buffer.byteLength||view.getUint32(16,true)!==0x4e4f534a)throw new Error('GLB清单区块无效');
  const manifest=JSON.parse(new TextDecoder().decode(buffer.slice(20,20+length)));
  if(manifest.asset?.version!=='2.0')throw new Error('不支持的GLB版本');
  if([...(manifest.buffers||[]),...(manifest.images||[])].some(x=>x.uri&&!x.uri.startsWith('data:')))throw new Error('资产包含外部资源，请提供自包含GLB');
  return manifest;
}
