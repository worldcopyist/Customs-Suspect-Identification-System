// Reproducible, offline runtime assets from the pinned npm dependency.
import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
await mkdir('vendor/three',{recursive:true});
for(const name of ['three.module.js','three.core.js'])await copyFile('node_modules/three/build/'+name,'vendor/three/'+name);
for(const [folder,name] of [['loaders','GLTFLoader.js'],['utils','BufferGeometryUtils.js'],['utils','SkeletonUtils.js']]){
  let source=await readFile(`node_modules/three/examples/jsm/${folder}/${name}`,'utf8');
  source=source.replaceAll("from 'three'","from './three.module.js'").replaceAll("from '../utils/","from './");
  await writeFile('vendor/three/'+name,source);
}
await copyFile('node_modules/three/LICENSE','vendor/three/LICENSE');
