export const state={user:null,csrf:null,portal:'CLIENT',route:'dashboard',restricted:false};
export const pages=new Map();
export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const manager=()=>['ADMIN','SUPER_ADMIN'].includes(state.user?.role);
export const can=p=>manager()||state.user?.permissions?.includes(p);
export const date=v=>v?new Date(/[zZ]|[+-]\d\d:\d\d$/.test(v)?v:v+'Z').toLocaleString('zh-CN',{hour12:false}):'—';
export const uuid=()=>{const b=new Uint8Array(16);crypto.getRandomValues(b);b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;return [...b].map((n,i)=>([4,6,8,10].includes(i)?'-':'')+n.toString(16).padStart(2,'0')).join('');};
const pendingKeys=new Map();
export async function api(path,options={}){
  const method=options.method||'GET',write=!['GET','HEAD'].includes(method),body=options.body;
  const signature=method+path+(body instanceof FormData?'multipart':JSON.stringify(body??{}));
  const headers=new Headers(options.headers||{});
  if(write){if(state.csrf)headers.set('X-CSRF-Token',state.csrf);if(!headers.has('Idempotency-Key')){if(!pendingKeys.has(signature))pendingKeys.set(signature,uuid());headers.set('Idempotency-Key',pendingKeys.get(signature));}}
  if(body!==undefined&&!(body instanceof FormData))headers.set('Content-Type','application/json');
  if(options.background)headers.set('X-Background-Request','true');
  let response;
  try{response=await fetch('/api/v1'+path,{method,headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body),credentials:'same-origin',signal:options.signal});}
  catch(e){if(e.name==='AbortError')throw e;throw new Error('无法连接本地服务，请检查服务是否运行及访问地址；未自动重试本次操作。');}
  if(response.status===204){pendingKeys.delete(signature);return null;}
  if(options.raw&&response.ok){pendingKeys.delete(signature);return response;}
  const payload=await response.json().catch(()=>({error:{message:'服务器返回了非预期内容'}}));
  if(!response.ok){
    if(payload.error?.code==='CSRF_INVALID'&&!options.retried){state.csrf=(await api('/auth/csrf')).csrf_token;headers.set('X-CSRF-Token',state.csrf);return api(path,{...options,headers,retried:true});}
    const err=new Error((payload.error?.message||'请求失败')+(payload.request_id?' · 请求编号 '+payload.request_id:''));err.code=payload.error?.code;err.status=response.status;err.requestId=payload.request_id;err.details=payload.error?.details;
    if(response.status===401&&state.user&&!['/auth/login','/auth/password'].includes(path)){state.user=null;state.restricted=false;showAuth('login',err.message);}
    if(err.code==='PASSWORD_CHANGE_REQUIRED'){state.user=null;state.restricted=true;showAuth('password');}
    throw err;
  }
  pendingKeys.delete(signature);return payload.data;
}
export const write=(path,body={},method='POST',options={})=>api(path,{method,body,...options});
let lastDiagnostic=0;
function reportClientError(event_code){
  if(!state.user||!state.csrf||Date.now()-lastDiagnostic<60000)return;
  lastDiagnostic=Date.now();
  // Never send the exception message/stack, page text, input values or URLs.
  write('/client-diagnostics',{event_code,module:'application'},'POST',{background:true}).catch(()=>{});
}
window.addEventListener('error',()=>reportClientError('SCRIPT_ERROR'));
window.addEventListener('unhandledrejection',()=>reportClientError('UNHANDLED_REJECTION'));
export function toast(message){const t=document.querySelector('#toast');t.textContent=message;t.classList.add('shown');setTimeout(()=>t.classList.remove('shown'),6500);}
export function errorView(error){return `<div class="error" role="alert">${esc(error.message||error)}</div>`;}
export function field(label,name,value='',type='text',extra=''){return `<label>${esc(label)}<span class="input-wrap"><input name="${name}" type="${type}" value="${esc(value)}" ${extra}>${type==='password'?`<button type="button" data-global="eye" class="eye" aria-label="显示密码" aria-pressed="false">◉</button>`:''}</span></label>`;}
export const area=(label,name,value='',extra='')=>`<label>${esc(label)}<textarea name="${name}" ${extra}>${esc(value)}</textarea></label>`;
export function select(label,name,options,value='',extra=''){return `<label>${esc(label)}<select name="${name}" ${extra}>${options.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;}
export const btn=(title,action='',extra='')=>`<button type="button" ${action?`data-action="${action}"`:''} ${extra}>${title}</button>`;
export const nav=(title,route)=>`<button type="button" data-nav="${route}" class="link">${title}</button>`;
export const card=(body,title='')=>`<section class="card">${title?`<h2>${title}</h2>`:''}${body}</section>`;
export const empty=t=>`<div class="empty">${esc(t)}</div>`;
export const query=o=>'?'+new URLSearchParams(Object.entries(o).filter(([,v])=>v!==''&&v!=null));
export async function all(path,options={}){let items=[],page=1;while(true){const data=await api(path+(path.includes('?')?'&':'?')+`page=${page}&page_size=100`,options);items.push(...data.items);if(items.length>=data.total||!data.items.length)return items;page++;}}
export function modal(title,body,submit,label='保存'){
  const dialog=document.createElement('dialog');dialog.innerHTML=`<form><header><h2>${esc(title)}</h2><button type="button" data-close aria-label="关闭">×</button></header><div class="dialog-body">${body}</div><div class="form-error"></div><footer><button type="button" data-close>取消</button><button type="submit" class="primary">${label}</button></footer></form>`;
  document.body.append(dialog);dialog.showModal();dialog.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>dialog.close());dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();e.stopPropagation();const form=e.currentTarget;if(!form.reportValidity())return;const button=form.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;form.querySelector('.form-error').textContent='';try{await submit(new FormData(form),dialog);dialog.close();}catch(err){form.querySelector('.form-error').innerHTML=errorView(err);}finally{button.disabled=false;}};return dialog;
}
const titles={dashboard:'工作台',image:'图片识别',camera:'摄像头识别',records:'检测记录',persons:'人员名单',communications:'内部通讯',assistant:'智能助手 / 数字人',users:'用户与权限',providers:'云端服务',agents:'多智能体',knowledge:'实训资料',operations:'运维与审计',bigscreen:'管理数据大屏',chatsearch:'聊天检索与导出',profile:'个人中心'};
const perm={dashboard:'detection.read',image:'detection.image',camera:'detection.camera',records:'detection.read',persons:'person.read',communications:'chat.use',assistant:'assistant.use'};
const adminPages=['bigscreen','users','providers','agents','knowledge','chatsearch','operations'];
let cleanup=()=>{},generation=0,current=null;
export async function navigate(route){
  if(!state.user)return;const base=route.split('/')[0];
  if((adminPages.includes(base)&&!manager())||(perm[base]&&!can(perm[base]))){toast('没有此页面权限');return;}
  cleanup();cleanup=()=>{};const gen=++generation;state.route=route;sessionStorage.setItem('last-route',route);history.replaceState(null,'','#'+route);
  document.querySelector('#app').innerHTML=`<div class="shell"><aside><div class="brand">⌜ 海关视觉实训<small>智能识别系统 · V1.2</small></div><nav>${Object.entries(perm).filter(([,p])=>can(p)).map(([key])=>nav(titles[key],key)).join('')}${manager()?'<div class="nav-label">管理中心</div>'+adminPages.map(key=>nav(titles[key],key)).join(''):''}</nav><small class="side-note">课程实训 · 人工复核<br>非身份确认或执法结论</small></aside><div class="workspace"><header class="topbar"><div>工作空间 / ${esc(titles[base]||'记录详情')}</div><div class="row"><span class="tag">${state.portal==='ADMIN'?'管理端':'用户端'}</span>${nav(esc(state.user.display_name)+' ▾','profile')}</div></header><main id="view"><h1>${esc(titles[base]||'记录详情')}</h1><div id="page-error"></div><div id="page-content">正在加载…</div></main></div></div>${can('chat.use')?'<button class="floating" data-global="chat">通讯 <span id="unread-badge">0</span></button>':''}`;
  document.querySelectorAll('aside [data-nav]').forEach(x=>x.classList.toggle('active',x.dataset.nav===base));
  const handlers={},disposers=[];
  current={gen,handlers};const context={route,active:()=>gen===generation,set:html=>{if(gen===generation)document.querySelector('#page-content').innerHTML=html;},on:(action,fn)=>handlers[action]=fn,dispose:fn=>disposers.push(fn),poll:(fn,ms)=>{let busy=false;const id=setInterval(async()=>{if(busy||gen!==generation||document.hidden)return;busy=true;try{await fn();}catch(err){if(gen===generation)document.querySelector('#page-error').innerHTML=errorView(err);}finally{busy=false;}},ms);disposers.push(()=>clearInterval(id));}};
  cleanup=()=>{for(const fn of disposers)fn();};
  try{const page=pages.get(base);if(!page)throw new Error('页面尚未注册');await page(context);}catch(err){if(context.active())context.set(errorView(err));}
}
async function action(e){
  const button=e.target.closest('[data-action]');if(!button||!current)return;
  const fn=current.handlers[button.dataset.action];if(!fn)return;
  if(e.type==='submit')e.preventDefault();else if(button.tagName==='FORM')return;
  const target=button.tagName==='FORM'?button.querySelector('[type=submit]'):button;if(target?.disabled)return;
  if(target)target.disabled=true;
  try{await fn(button,e);}catch(err){toast(err.message);const area=document.querySelector('#page-error');if(area)area.innerHTML=errorView(err);}finally{if(target)target.disabled=false;}
}
document.addEventListener('submit',action);
document.addEventListener('click',e=>{
  const eye=e.target.closest('[data-global="eye"]');if(eye){const input=eye.parentElement.querySelector('input');input.type=input.type==='password'?'text':'password';eye.setAttribute('aria-pressed',String(input.type==='text'));eye.setAttribute('aria-label',input.type==='text'?'隐藏密码':'显示密码');return;}
  const go=e.target.closest('[data-nav]');if(go){navigate(go.dataset.nav);return;}
  if(e.target.closest('[data-global="chat"]')){window.dispatchEvent(new Event('open-communications'));return;}
  action(e);
});
export function showAuth(mode='login',message=''){
  cleanup();generation++;current=null;
  window.dispatchEvent(new Event('session-cleared'));
  document.querySelectorAll('dialog').forEach(d=>d.close());
  const pwd=mode==='password',reg=mode==='register';
  document.querySelector('#app').innerHTML=`<div class="auth"><section class="auth-visual"><span class="tag">课程实训</span><h1>海关场景<br>视觉智能识别系统</h1><p>检测 · 留档 · 人工复核</p></section><section class="auth-panel"><div class="auth-inner"><div class="logo">⌜</div><h1>${pwd?'修改初始密码':reg?'创建用户账户':'欢迎登录'}</h1><p class="muted">${pwd?'登录验证成功后，需要完成初始密码修改':'请选择入口，使用真实系统账户登录'}</p>${pwd?'':`<div class="tabs"><button type="button" data-portal="CLIENT" class="${state.portal==='CLIENT'?'active':''}">用户端</button><button type="button" data-portal="ADMIN" class="${state.portal==='ADMIN'?'active':''}">管理端</button></div>`}<form id="auth-form">${pwd?'':field('用户名','username','','text','required autocomplete="username"')}${reg?field('显示名称','display_name','','text','required maxlength="50"'):''}${field(pwd?'当前密码':'密码',pwd?'current_password':'password','','password',`required autocomplete="${reg?'new-password':'current-password'}" ${reg?'minlength="12"':''} maxlength="128"`)}${pwd?field('新密码（12–128 位）','new_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"'):''}${pwd||reg?field('确认密码',pwd?'new_password_confirm':'password_confirm','','password','required minlength="12" maxlength="128" autocomplete="new-password"'):''}<div id="auth-error" class="form-error">${esc(message)}</div><button class="primary" type="submit">${pwd?'确认修改':reg?'注册':'登录'}</button></form>${!pwd&&state.portal==='CLIENT'?`<button id="auth-switch" class="link">${reg?'已有账户？返回登录':'没有账户？立即注册'}</button>`:''}${pwd?'<button id="auth-logout" class="link">退出，返回登录</button>':''}<p class="notice">仅用于课程实训，检测结果需人工复核。<br>新密码 12–128 位；密码不自动去除空格。</p></div></section></div>`;
  document.querySelectorAll('[data-portal]').forEach(x=>x.onclick=()=>{state.portal=x.dataset.portal;sessionStorage.setItem('portal',state.portal);showAuth();});
  const sw=document.querySelector('#auth-switch');if(sw)sw.onclick=()=>showAuth(reg?'login':'register');
  const out=document.querySelector('#auth-logout');if(out)out.onclick=logout;
  document.querySelector('#auth-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;if(!form.reportValidity())return;const b=form.querySelector('[type=submit]');b.disabled=true;const data=Object.fromEntries(new FormData(form));try{
    if(!state.csrf)state.csrf=(await api('/auth/csrf')).csrf_token;
    if(pwd){await write('/auth/password',data);state.csrf=(await api('/auth/csrf')).csrf_token;state.restricted=false;showAuth('login','密码已修改，请用新密码登录。');}
    else if(reg){await write('/auth/register',data);showAuth('login','注册成功，请登录。');}
    else{const out=await write('/auth/login',{...data,portal:state.portal});state.csrf=out.csrf_token;if(out.session_phase==='CHANGE_PASSWORD'||out.session_phase==='PASSWORD_CHANGE_REQUIRED'){state.restricted=true;showAuth('password');}else{state.user=out.user;state.restricted=false;pendingKeys.clear();await navigate(state.portal==='ADMIN'?'bigscreen':'dashboard');}}
  }catch(err){document.querySelector('#auth-error').textContent=err.message;}finally{b.disabled=false;}};
}
export async function logout(){
  try{await write('/auth/logout');}
  catch(err){if(err.status!==401){toast('退出未完成，服务器尚未确认撤销会话。'+err.message);return;}}
  state.user=null;state.restricted=false;state.csrf=null;pendingKeys.clear();sessionStorage.removeItem('last-route');showAuth();
  try{state.csrf=(await api('/auth/csrf')).csrf_token;}catch(err){toast(err.message);}
}
pages.set('profile',async ctx=>{
  state.user=await api('/auth/me');const u=state.user;
  ctx.set(`<div class="grid two">${card(`<p>@${esc(u.username)} · ${esc(u.role)}</p><form data-action="profile-save">${field('显示名称','display_name',u.display_name,'text','required maxlength="50"')}<button class="primary" type="submit">保存资料</button></form>`,'个人资料')}${card(`<form data-action="password-save">${field('当前密码','current_password','','password','required autocomplete="current-password"')}${field('新密码（12–128 位）','new_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}${field('确认新密码','new_password_confirm','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}<p class="muted">修改后撤销所有旧登录会话。</p><button class="primary" type="submit">修改密码</button></form>`,'管理密码')}</div><div class="toolbar">${btn('退出登录','logout')}</div>`);
  ctx.on('profile-save',async form=>{state.user=await write('/auth/me',{...Object.fromEntries(new FormData(form)),expected_version:state.user.version},'PATCH');toast('资料已保存');});
  ctx.on('password-save',async form=>{await write('/auth/password',Object.fromEntries(new FormData(form)));await logout();toast('密码已修改，请重新登录');});ctx.on('logout',logout);
});
export async function boot(){
  if(location.protocol==='file:'){document.querySelector('#app').innerHTML=card('<h1>请通过本地服务访问系统</h1><p>直接打开 HTML 无法连接后端。</p><a href="http://127.0.0.1:8000/">打开 http://127.0.0.1:8000/</a>');return;}
  state.portal=sessionStorage.getItem('portal')||'CLIENT';
  try{state.csrf=(await api('/auth/csrf')).csrf_token;state.user=await api('/auth/me');await navigate(location.hash.slice(1)||'dashboard');}catch(err){if(err.code==='PASSWORD_CHANGE_REQUIRED'){state.restricted=true;showAuth('password');}else showAuth('login',err.code==='UNAUTHENTICATED'?'':err.message);}
  setInterval(async()=>{if(!state.user||state.restricted)return;try{await write('/presence/heartbeat',{},'POST',{background:true});}catch(err){if(state.user)toast(err.message);}},30000);
}
