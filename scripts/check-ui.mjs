import assert from 'node:assert/strict';
import {markdown} from '../ui/markdown.js';
import {mergeMessages} from '../ui/chat-history.js';
import {glbManifest} from '../ui/avatar-validation.js';
for(const input of ['<script>alert(1)</script>','<img src=x onerror=alert(1)>','[打开](javascript:alert(1))','![远程](https://example.com/private.png)','<iframe src="https://example.com"></iframe>']){
  const html=markdown(input);
  assert(!/<(?:script|img|iframe)\b/i.test(html),html);
  assert(!/href\s*=\s*["']?javascript:/i.test(html),html);
}
assert(markdown('# 标题').includes('<h'));
assert(markdown('**重点**').includes('<strong>'));
assert.equal(markdown('\\*原样\\* \\[K1\\]'),'<'+'p>*原样* [K1]</p>');
assert.equal(markdown('`**原样代码**`'),'<p><code>**原样代码**</code></p>');
console.log('PASS: safe Markdown subset rejects executable HTML and remote images');
const merged=mergeMessages([{seq:'9007199254740993',content:'old'}],[{seq:'9007199254740992',content:'earlier'},{seq:'9007199254740993',content:'updated'},{seq:'9007199254740994',content:'new'}]);
assert.deepEqual(merged.map(x=>x.seq),['9007199254740992','9007199254740993','9007199254740994']);
assert.equal(merged[1].content,'updated');
assert.equal(mergeMessages(merged,merged).length,3);
console.log('PASS: paged chat merge preserves exact sequence order and deduplicates refreshes');
function glb(manifest){let body=JSON.stringify(manifest);body=body.padEnd(Math.ceil(body.length/4)*4,' ');const buffer=new ArrayBuffer(20+body.length),view=new DataView(buffer);[0x46546c67,2,buffer.byteLength,body.length,0x4e4f534a].forEach((x,i)=>view.setUint32(i*4,x,true));new Uint8Array(buffer,20).set(new TextEncoder().encode(body));return buffer;}
assert.equal(glbManifest(glb({asset:{version:'2.0'}})).asset.version,'2.0');
assert.throws(()=>glbManifest(new ArrayBuffer(5)));
assert.throws(()=>glbManifest(glb({asset:{version:'2.0'},images:[{uri:'https://example.com/texture.png'}]})));
assert.throws(()=>glbManifest(glb({asset:{version:'2.0'},buffers:[{uri:'../external.bin'}]})));
const malformed=glb({asset:{version:'2.0'}});new DataView(malformed).setUint32(12,999999,true);assert.throws(()=>glbManifest(malformed));
console.log('PASS: GLB header validation rejects truncation and external asset references');
