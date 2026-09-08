const liveRuntime = { records: null, recordsLoading: false, imageFile: null, imageDetection: null, imagePolling: null, camera: null, menuOpen: false };

function liveEscape(value) { return esc(value == null ? '' : value); }
function liveDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'; }
function liveState(value) { return ({ QUEUED: '排队中', RUNNING: '识别中', SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消' })[value] || value; }
function liveReview(value) { return ({ PENDING: '待复核', NOT_APPLICABLE: '无需复核', REVIEWED_KEEP: '已复核—保留', REVIEWED_FALSE_POSITIVE: '已复核—误报' })[value] || value; }
function liveBadge(value, type) { return '<span class="badge ' + (type || 'gray') + '">' + liveEscape(value) + '</span>'; }
function liveRows(items) {
  if (!items || !items.length) return '<tr><td colspan="6" class="empty-cell">暂无检测记录</td></tr>';
  return items.map(function(item) {
    const result = item.state === 'SUCCEEDED' ? '检出 ' + item.boxes.length + ' 个目标' : liveState(item.state);
    return '<tr><td>' + liveEscape(item.id.slice(0, 8)) + '</td><td>' + (item.source === 'CAMERA' ? '摄像头' : '图片') + '</td><td>' + liveDate(item.created_at) + '</td><td>' + liveEscape(result) + '</td><td>' + liveBadge(liveReview(item.review_status), item.review_status === 'PENDING' ? 'orange' : 'gray') + '</td><td><a data-page="records">查看</a></td></tr>';
  }).join('');
}

function layout(content) {
  const user = state.user || { display_name: '当前用户', username: '', role: 'USER' };
  const initials = liveEscape(user.display_name).slice(0, 1) || '用';
  const menu = liveRuntime.menuOpen ? '<div class="user-menu"><strong>' + liveEscape(user.display_name) + '</strong><small>' + liveEscape(user.username) + '</small><a data-page="profile">个人中心</a><a data-action="live-logout">退出登录</a></div>' : '';
  const navItems = [['dashboard', '▦', '工作台'], ['camera', '▣', '摄像头识别'], ['image', '▧', '图片识别'], ['records', '▤', '检测记录'], ['digital-human', '◉', '数字人'], ['communications', '▣', '内部通讯']];
  if (user.role !== 'USER') navItems.push(['llm-settings', '⚙', '大模型设置']);
  app.innerHTML = '<aside class="sidebar"><a class="logo" data-page="dashboard"><span class="logo-icon">⌜</span><b>海关视觉<small>智能识别系统</small></b></a><nav>' + navItems.map(function(item) { return '<a data-page="' + item[0] + '" class="' + (state.page === item[0] ? 'active' : '') + '"><i>' + item[1] + '</i>' + item[2] + '</a>'; }).join('') + '</nav></aside><section class="shell"><header><div class="crumb">⌂　›　' + ({ dashboard: '工作台', camera: '摄像头识别', image: '图片识别', records: '检测记录', profile: '个人中心', 'digital-human': '数字人助手', communications: '内部通讯', 'llm-settings': '大模型设置' })[state.page] + '</div><div class="topbar"><span class="env">业务环境</span><button class="user-trigger" data-action="live-user-menu"><span class="avatar">' + initials + '</span><span><strong>' + liveEscape(user.display_name) + '</strong><small>' + roleLabel(user.role) + '</small></span>⌄</button>' + menu + '</div></header><section class="content">' + content + '</section></section>';
}

function dashboard() {
  const records = liveRuntime.records || [];
  const pending = records.filter(function(item) { return item.review_status === 'PENDING'; }).length;
  return '<div class="title-row"><div><h1>工作台</h1><p>当前账户的真实检测任务与记录</p></div><a data-page="records">查看检测记录　›</a></div><section class="card launch"><h2>开启一次检测</h2><div class="launch-grid"><div class="launch-item"><span class="round">▣</span><div><h2>摄像头识别</h2><p>使用本机摄像头进行实时检测</p></div>' + button('开启摄像头', 'primary', 'page-camera') + '</div><div class="launch-item"><span class="round">▧</span><div><h2>图片识别</h2><p>选择一张本地图片后发起检测</p></div>' + button('选择图片', 'primary', 'page-image') + '</div></div></section><div class="stats"><div class="card stat orange"><span>▤</span><div><b>待复核</b><strong>' + pending + '</strong></div></div><div class="card stat blue"><span>▤</span><div><b>检测记录</b><strong>' + records.length + '</strong></div></div><div class="card stat teal"><span>✓</span><div><b>已完成</b><strong>' + records.filter(function(item) { return item.state === 'SUCCEEDED'; }).length + '</strong></div></div></div><section class="card padded"><h2>最近检测记录</h2><table class="live-table"><thead><tr><th>记录编号</th><th>来源</th><th>创建时间</th><th>检测结果</th><th>复核状态</th><th>操作</th></tr></thead><tbody>' + liveRows(records.slice(0, 5)) + '</tbody></table></section>';
}

function camera() {
  const active = Boolean(liveRuntime.camera);
  const status = active ? '<span class="live">●　实时采集中</span>' : '<span class="muted">尚未开启摄像头</span>';
  const result = active && liveRuntime.camera.result ? '<p class="camera-result">最近帧：检出 ' + liveRuntime.camera.result.boxes.length + ' 个目标，处理 ' + Math.round(liveRuntime.camera.result.inference_ms) + ' ms</p>' : '<p class="muted">点击“开启摄像头”后授权浏览器使用本机摄像头。</p>';
  return '<div class="title-row"><div><h1>摄像头识别</h1><p>本机实时画面；检测结果仅供人工复核</p></div></div><section class="card device"><label>设备<select disabled><option>浏览器默认摄像头</option></select></label>' + status + button(active ? '停止检测' : '开启摄像头', active ? 'outline' : 'primary', active ? 'live-camera-stop' : 'live-camera-start') + '</section><section class="card padded"><div class="live-video-wrap"><video id="live-camera-video" autoplay muted playsinline></video><div class="video-placeholder ' + (active ? 'hidden' : '') + '">实时画面将在开启摄像头后显示</div></div>' + result + '</section>';
}

function image() {
  const file = liveRuntime.imageFile;
  const detection = liveRuntime.imageDetection;
  let body = '<div class="upload-drop" data-action="live-image-browse"><strong>点击选择需要识别的图片</strong><span>支持 JPG、JPEG、PNG；单张上传</span></div><input id="live-image-file" type="file" accept="image/jpeg,image/png" hidden>';
  if (file) body = '<div class="upload-selected"><strong>' + liveEscape(file.name) + '</strong><small>' + Math.ceil(file.size / 1024) + ' KB</small><a data-action="live-image-browse">重新选择</a></div><input id="live-image-file" type="file" accept="image/jpeg,image/png" hidden>' + button('开始识别', 'primary', 'live-image-detect');
  if (detection) body += '<section class="card padded detection-status"><h2>' + liveState(detection.state) + '</h2><p>记录编号：' + liveEscape(detection.id) + '</p><p>检出目标：' + detection.boxes.length + '</p>' + (detection.error_code ? '<p class="danger">失败原因：' + liveEscape(detection.error_code) + '</p>' : '') + '</section>';
  return '<div class="title-row"><div><h1>图片识别</h1><p>选择本地图片，主动发起检测</p></div></div><section class="card padded image-live">' + body + '</section>';
}

function records() {
  const data = liveRuntime.records;
  const records = data || [];
  return '<div class="title-row"><div><h1>检测记录</h1><p>仅显示真实保存的检测任务</p></div>' + button('刷新', 'outline', 'live-records-refresh') + '</div><section class="card filter live-filter"><label>来源<select disabled><option>全部</option></select></label><label>时间<input disabled placeholder="全部时间"/></label><label>复核状态<select disabled><option>全部</option></select></label></section><p class="count">共 ' + records.length + ' 条' + (liveRuntime.recordsLoading ? '，加载中…' : '') + '</p><table class="live-table"><thead><tr><th>记录编号</th><th>来源</th><th>创建时间</th><th>检测结果</th><th>复核状态</th><th>操作</th></tr></thead><tbody>' + liveRows(records) + '</tbody></table>';
}

function profile() {
  const user = state.user || {};
  return '<div class="title-row"><div><h1>个人中心</h1><p>当前已登录账户</p></div></div><section class="card padded account-card"><h2>' + liveEscape(user.display_name) + '</h2><p>用户名：' + liveEscape(user.username) + '</p><p>角色：' + roleLabel(user.role) + '</p><hr><h2>管理密码</h2><label>当前密码<input id="profile-current-password" type="password"></label><label>新密码（至少 8 位）<input id="profile-new-password" type="password"></label><label>确认新密码<input id="profile-confirm-password" type="password"></label><button class="btn primary" data-action="live-profile-password">修改密码</button>' + button('退出登录', 'danger-outline', 'live-logout') + '</section>';
}

function render() {
  if (['login', 'register', 'change'].includes(state.page)) { login(); addPasswordVisibilityControls(); return; }
  const page = { dashboard: dashboard, camera: camera, image: image, records: records, profile: profile, 'digital-human': digitalHuman, communications: communications, 'llm-settings': llmSettings }[state.page] || dashboard;
  layout(page());
  if ((state.page === 'dashboard' || state.page === 'records') && !liveRuntime.recordsLoading && liveRuntime.records === null) setTimeout(loadLiveRecords, 0);
  if (state.page === 'camera' && liveRuntime.camera) setTimeout(attachLiveVideo, 0);
}

async function loadLiveRecords() {
  liveRuntime.recordsLoading = true;
  try { liveRuntime.records = (await api('/detections?page=1&page_size=100')).items || []; } catch (error) { toast(error.message); liveRuntime.records = []; }
  liveRuntime.recordsLoading = false;
  if (state.page === 'dashboard' || state.page === 'records') render();
}
async function apiForm(path, form) {
  if (!state.csrf) await refreshCsrf();
  const headers = { 'X-CSRF-Token': state.csrf, Origin: apiOrigin, 'Idempotency-Key': idempotencyKey() };
  const response = await fetch('/api/v1' + path, { method: 'POST', headers: headers, credentials: 'same-origin', body: form });
  const payload = await response.json().catch(function() { return null; });
  if (!response.ok) { const error = new Error((payload && payload.error && payload.error.message) || '请求失败'); error.code = payload && payload.error && payload.error.code; throw error; }
  return payload.data;
}
function attachLiveVideo() {
  const video = document.querySelector('#live-camera-video');
  if (video && liveRuntime.camera) video.srcObject = liveRuntime.camera.stream;
}
async function startLiveCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('当前浏览器不支持摄像头访问');
  const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  try {
    const session = await api('/camera/sessions', 'POST', { client_label: '浏览器实时摄像头' });
    liveRuntime.camera = { stream: stream, sessionId: session.id, frameSeq: 0, result: null };
    render();
    liveRuntime.camera.timer = setInterval(sendLiveFrame, 1500);
    liveRuntime.camera.heartbeat = setInterval(function() { if (liveRuntime.camera) api('/camera/sessions/' + liveRuntime.camera.sessionId + '/heartbeat', 'POST', {}).catch(stopLiveCamera); }, 15000);
  } catch (error) {
    stream.getTracks().forEach(function(track) { track.stop(); });
    throw error;
  }
}
async function sendLiveFrame() {
  const current = liveRuntime.camera;
  const video = document.querySelector('#live-camera-video');
  if (!current || !video || !video.videoWidth) return;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  const blob = await new Promise(function(resolve) { canvas.toBlob(resolve, 'image/jpeg', 0.8); });
  if (!blob || !liveRuntime.camera) return;
  const form = new FormData(); form.append('file', blob, 'camera-frame.jpg'); form.append('frame_seq', String(++current.frameSeq));
  try {
    current.result = await apiForm('/camera/sessions/' + current.sessionId + '/frames', form);
    if (state.page === 'camera') render();
  } catch (error) {
    if (error.code !== 'FRAME_IN_FLIGHT' && error.code !== 'MODEL_UNAVAILABLE') toast(error.message);
  }
}
async function stopLiveCamera() {
  const current = liveRuntime.camera;
  if (!current) return;
  clearInterval(current.timer); clearInterval(current.heartbeat);
  current.stream.getTracks().forEach(function(track) { track.stop(); });
  liveRuntime.camera = null;
  try { await api('/camera/sessions/' + current.sessionId + '/stop', 'POST', {}); } catch (_) {}
  if (state.page === 'camera') render();
}
async function detectSelectedImage() {
  const file = liveRuntime.imageFile;
  if (!file) throw new Error('请先选择图片');
  const form = new FormData(); form.append('file', file); form.append('purpose', 'DETECTION_IMAGE');
  const media = await apiForm('/media', form);
  liveRuntime.imageDetection = await api('/detections/images', 'POST', { media_id: media.id });
  render();
  clearInterval(liveRuntime.imagePolling);
  liveRuntime.imagePolling = setInterval(async function() {
    if (!liveRuntime.imageDetection || ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(liveRuntime.imageDetection.state)) { clearInterval(liveRuntime.imagePolling); return; }
    try {
      liveRuntime.imageDetection = await api('/detections/' + liveRuntime.imageDetection.id);
      if (state.page === 'image') render();
      if (['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(liveRuntime.imageDetection.state)) { clearInterval(liveRuntime.imagePolling); liveRuntime.records = null; }
    } catch (error) { clearInterval(liveRuntime.imagePolling); toast(error.message); }
  }, 1200);
}

document.addEventListener('change', function(event) {
  const input = event.target;
  if (!input || input.id !== 'live-image-file') return;
  const file = input.files && input.files[0];
  if (!file) return;
  liveRuntime.imageFile = file; liveRuntime.imageDetection = null; render();
});
document.addEventListener('click', async function(event) {
  const control = event.target.closest('[data-action]');
  const action = control && control.dataset.action;
  if (!['live-user-menu', 'live-logout', 'live-camera-start', 'live-camera-stop', 'live-image-browse', 'live-image-detect', 'live-records-refresh'].includes(action)) return;
  event.preventDefault(); event.stopPropagation();
  try {
    if (action === 'live-user-menu') { liveRuntime.menuOpen = !liveRuntime.menuOpen; render(); return; }
    if (action === 'live-logout') { await stopLiveCamera(); try { await api('/auth/logout', 'POST', {}); } catch (_) {} state.user = null; state.page = 'login'; await refreshCsrf(); render(); return; }
    if (action === 'live-camera-start') { await startLiveCamera(); return; }
    if (action === 'live-camera-stop') { await stopLiveCamera(); return; }
    if (action === 'live-image-browse') { document.querySelector('#live-image-file').click(); return; }
    if (action === 'live-image-detect') { await detectSelectedImage(); return; }
    if (action === 'live-records-refresh') { liveRuntime.records = null; await loadLiveRecords(); }
  } catch (error) { toast(error.message); }
}, true);

render();

/* Restored LLM, digital-human and internal-communication modules. */
liveRuntime.avatar = null; liveRuntime.assistant = { conversation: null, messages: [] }; liveRuntime.chat = { users: [], conversations: [], selected: null, messages: [] }; liveRuntime.providers = [];
function digitalHuman() {
  const manager = state.user && state.user.role !== 'USER'; const asset = liveRuntime.avatar && liveRuntime.avatar.asset;
  const visual = asset && asset.mime_type.startsWith('image/') ? '<img src="' + asset.content_url + '" alt="已上传数字人模型预览">' : '<img src="/assets/digital-human-adult-male.png" alt="成年男性数字人默认模型">';
  const upload = manager ? '<input id="live-avatar-file" type="file" accept=".glb,.gltf,image/png,image/jpeg" hidden><button class="btn outline" data-action="live-avatar-browse">上传并替换模型</button><p class="muted">支持 GLB / GLTF（存储为模型资源）及 PNG / JPG（可直接作为页面预览），最大 25MB。</p>' : '<p class="muted">数字人模型由管理员统一维护。</p>';
  return '<div class="title-row"><div><h1>数字人助手</h1><p>与已配置的大模型进行文本交流</p></div></div><div class="digital-grid"><section class="card padded avatar-panel">' + visual + '<h2>成年男性数字人</h2>' + upload + '</section><section class="card padded assistant-panel"><h2>对话窗口</h2><div class="assistant-messages">' + (liveRuntime.assistant.messages.length ? liveRuntime.assistant.messages.map(function(m){return '<p class="message '+(m.role==='USER'?'mine':'')+'">'+liveEscape(m.content)+'</p>';}).join('') : '<p class="muted">输入问题后，系统会先显示云端发送内容摘要，您确认后才会调用大模型。</p>') + '</div><textarea id="live-assistant-input" placeholder="请输入要咨询的问题"></textarea><div class="button-row"><button class="btn primary" data-action="live-assistant-send">发送给大模型</button></div></section></div>';
}
function communications() {
  const chat = liveRuntime.chat, users = chat.users, groups = chat.conversations.filter(function(item) { return item.type === 'GROUP' && item.state === 'ACTIVE'; });
  const userItems = users.length ? users.map(function(user) { return '<button class="contact-item" data-comm="direct" data-user-id="' + user.id + '">' + liveEscape(user.display_name) + '<small>@' + liveEscape(user.username) + '</small></button>'; }).join('') : '<p class="muted">暂无其他局域网账户。</p>';
  const groupItems = groups.length ? groups.map(function(group) { return '<button class="contact-item" data-comm="group" data-conversation-id="' + group.id + '">群　' + liveEscape(group.title) + '<small>' + group.member_count + ' 名成员</small></button>'; }).join('') : '<p class="muted">暂无群聊。</p>';
  const selected = chat.selected, msgs = selected ? (chat.messages.length ? chat.messages.map(function(m) { return '<p class="message ' + (m.sender_id === state.user.id ? 'mine' : '') + '"><b>' + liveEscape(m.sender_display_name) + '：</b>' + liveEscape(m.content) + '</p>'; }).join('') : '<p class="muted">暂无消息</p>') : '<p class="muted">选择左侧联系人或群聊开始通讯。</p>';
  const composer = chat.creatingGroup ? '<div class="group-create"><label>群聊名称<input id="group-title" maxlength="100" placeholder="例如：一组协同"></label><p>邀请联系人</p>' + (users.length ? users.map(function(user) { return '<label class="check"><input type="checkbox" name="group-members" value="' + user.id + '">' + liveEscape(user.display_name) + '（@' + liveEscape(user.username) + '）</label>'; }).join('') : '<p class="muted">需要至少一名其他真实账户才能建群。</p>') + '<button class="btn primary" data-comm="group-save">确认建立</button><button class="btn" data-comm="group-cancel">取消</button></div>' : '';
  const create = state.user && state.user.role !== 'USER' ? '<button class="btn outline" data-comm="group-create" ' + (users.length ? '' : 'disabled') + '>建立群聊</button>' : '';
  return '<div class="title-row"><div><h1>内部通讯</h1><p>仅限同一局域网内、本系统的真实账户与群聊</p></div>' + create + '</div><div class="communications"><section class="card padded contact-list"><h2>其他用户</h2>' + userItems + '<h2 class="group-heading">群聊</h2>' + groupItems + '</section><section class="card padded chat-panel">' + composer + '<h2>' + (selected ? '内部会话' : '选择联系人') + '</h2><div class="chat-messages">' + msgs + '</div>' + (selected ? '<textarea id="live-chat-input" placeholder="输入内部消息"></textarea><button class="btn primary" data-action="live-chat-send">发送</button>' : '') + '</section></div>';
}
function llmSettings() {
  const first = liveRuntime.providers[0]; const current = first || {}; const existing = first ? '<p class="notice small">已有配置：'+liveEscape(first.name)+' / '+liveEscape(first.model)+'；编辑保存会提交新版本。</p>' : '';
  return '<div class="title-row"><div><h1>大模型设置</h1><p>API 密钥会加密保存，界面只显示是否已配置。</p></div></div><section class="card padded llm-form">'+existing+'<label>厂商<select id="llm-provider"><option value="DEEPSEEK">DeepSeek</option><option value="QWEN">通义千问</option></select></label><label>配置名称<input id="llm-name" value="'+liveEscape(current.name||'默认大模型')+'"></label><label>API 地址<input id="llm-url" value="'+liveEscape(current.base_url||'https://api.deepseek.com')+'"></label><label>模型名称<input id="llm-model" value="'+liveEscape(current.model||'deepseek-chat')+'"></label><label>API Key<input id="llm-key" type="password" placeholder="'+(current.has_api_key?'已配置，留空则不更改':'请输入 API Key')+'"></label><label>温度 <input id="llm-temperature" type="number" min="0" max="2" step="0.1" value="'+(current.temperature==null?'0.7':current.temperature)+'"></label><label>最大输出 Token<input id="llm-tokens" type="number" min="256" max="4096" value="'+(current.max_output_tokens||2048)+'"></label><button class="btn primary" data-action="live-llm-save">保存配置</button>'+(first?'<button class="btn outline" data-action="live-llm-test">测试连接并启用</button>':'')+'<p class="muted">测试会向您设置的云端厂商发出一次最小文本请求；通过后自动启用。</p></section>';
}
async function loadExtras() { try { liveRuntime.avatar=await api('/digital-human/model'); } catch(_) {} try { liveRuntime.chat.users=(await api('/chat/users')).items||[]; liveRuntime.chat.conversations=(await api('/chat/conversations')).items||[]; } catch(_) {} if(state.user&&state.user.role!=='USER') try { liveRuntime.providers=(await api('/admin/llm/providers')).items||[]; } catch(_) {} if(['digital-human','communications','llm-settings'].includes(state.page)) oldRender(); }
document.addEventListener('click', async function(event) { const c=event.target.closest('[data-action]'), a=c&&c.dataset.action; if(!['live-avatar-browse','live-avatar-upload','live-chat-open','live-chat-send','live-assistant-send','live-llm-save','live-llm-test'].includes(a))return; event.preventDefault();event.stopPropagation();try { if(a==='live-avatar-browse'){document.querySelector('#live-avatar-file').click();return;} if(a==='live-chat-open'){let x=await api('/chat/direct-conversations','POST',{peer_user_id:c.dataset.userId});liveRuntime.chat.selected=x.id;liveRuntime.chat.messages=(await api('/chat/conversations/'+x.id+'/messages')).items;render();return;} if(a==='live-chat-send'){let v=document.querySelector('#live-chat-input').value.trim();if(v){await api('/chat/conversations/'+liveRuntime.chat.selected+'/messages','POST',{client_message_id:crypto.randomUUID(),content:v});liveRuntime.chat.messages=(await api('/chat/conversations/'+liveRuntime.chat.selected+'/messages')).items;render();}return;} if(a==='live-assistant-send'){let q=document.querySelector('#live-assistant-input').value.trim();if(!q)return;let conv=liveRuntime.assistant.conversation||await api('/assistant/conversations','POST',{title:'数字人对话'});liveRuntime.assistant.conversation=conv;let prep=await api('/assistant/requests/prepare','POST',{conversation_id:conv.id,mode:'GENERAL',question:q});if(!confirm('将问题发送至已配置的云端大模型，是否继续？'))return;await api('/assistant/requests/'+prep.id+'/confirm','POST',{payload_hash:prep.payload_hash,consent:true});toast('已提交大模型请求');return;} if(a==='live-llm-test'){let x=liveRuntime.providers[0];if(!confirm('将向云端厂商发起一次连接测试，是否继续？'))return;await api('/admin/llm/providers/'+x.id+'/test','POST',{consent_to_test:true,expected_version:x.version});await api('/admin/llm/providers/'+x.id,'PATCH',{enabled:true,expected_version:x.version});await loadExtras();toast('连接测试成功，已启用');return;} if(a==='live-llm-save'){let old=liveRuntime.providers[0], d={provider:document.querySelector('#llm-provider').value,name:document.querySelector('#llm-name').value,base_url:document.querySelector('#llm-url').value,model:document.querySelector('#llm-model').value,temperature:Number(document.querySelector('#llm-temperature').value),max_output_tokens:Number(document.querySelector('#llm-tokens').value)};let key=document.querySelector('#llm-key').value;if(old){d.expected_version=old.version;if(key)d.api_key=key;await api('/admin/llm/providers/'+old.id,'PATCH',d);}else{if(!key)throw new Error('新建配置必须填写 API Key');d.api_key=key;d.enabled=false;await api('/admin/llm/providers','POST',d);}await loadExtras();render();toast('配置已保存');}}catch(e){toast(e.message);}},true);
document.addEventListener('change',async function(e){if(e.target.id!=='live-avatar-file'||!e.target.files[0])return;try{let f=new FormData();f.append('file',e.target.files[0]);liveRuntime.avatar=await apiForm('/digital-human/model',f);render();toast('数字人模型已替换');}catch(x){toast(x.message);}});
document.addEventListener('click', async function(event) {
  const control = event.target.closest('[data-comm]');
  if (!control) return;
  event.preventDefault();
  try {
    const action = control.dataset.comm;
    if (action === 'group-create') { liveRuntime.chat.creatingGroup = true; render(); return; }
    if (action === 'group-cancel') { liveRuntime.chat.creatingGroup = false; render(); return; }
    if (action === 'direct') {
      const conversation = await api('/chat/direct-conversations', 'POST', { peer_user_id: control.dataset.userId });
      liveRuntime.chat.selected = conversation.id;
    } else if (action === 'group') {
      liveRuntime.chat.selected = control.dataset.conversationId;
    } else if (action === 'group-save') {
      const title = document.querySelector('#group-title').value.trim();
      const member_ids = Array.from(document.querySelectorAll('[name="group-members"]:checked')).map(function(input) { return input.value; });
      if (!title || !member_ids.length) throw new Error('请填写群聊名称并至少邀请一名联系人');
      const group = await api('/admin/chat/groups', 'POST', { title: title, member_ids: member_ids });
      liveRuntime.chat.creatingGroup = false; liveRuntime.chat.selected = group.id;
      await loadExtras();
    }
    if (liveRuntime.chat.selected) liveRuntime.chat.messages = (await api('/chat/conversations/' + liveRuntime.chat.selected + '/messages')).items;
    render();
  } catch (error) { toast(error.message); }
}, true);
document.addEventListener('click', async function(event) {
  const control = event.target.closest('[data-action]'), action = control && control.dataset.action;
  try {
    if (action === 'live-profile-password') {
      const current = document.querySelector('#profile-current-password').value, next = document.querySelector('#profile-new-password').value, confirmPassword = document.querySelector('#profile-confirm-password').value;
      validPassword(next, confirmPassword, '新密码');
      await api('/auth/password', 'POST', { current_password: current, new_password: next, new_password_confirm: confirmPassword });
      state.user = null; state.page = 'login'; await refreshCsrf(); render(); toast('密码已修改，请使用新密码重新登录');
    }
    if (action === 'live-chat-group') {
      const title = window.prompt('请输入群聊名称'); if (!title) return;
      const member_ids = liveRuntime.chat.users.map(function(user) { return user.id; });
      await api('/admin/chat/groups', 'POST', { title: title, member_ids: member_ids });
      await loadExtras(); toast('群聊已建立');
    }
    if (action === 'live-assistant-send') {
      setTimeout(async function() {
        if (!liveRuntime.assistant.conversation) return;
        try { liveRuntime.assistant.messages = (await api('/assistant/conversations/' + liveRuntime.assistant.conversation.id + '/messages?page_size=50')).items.filter(function(item){return !item.hidden;}).reverse(); if (state.page === 'digital-human') render(); } catch (_) {}
      }, 1800);
    }
  } catch (error) { toast(error.message); }
}, true);
document.addEventListener('click', function(event) {
  const control = event.target.closest('[data-action]');
  if (!control || control.dataset.action !== 'live-assistant-send') return;
  const input = document.querySelector('#live-assistant-input'), question = input && input.value.trim();
  if (!question) return;
  liveRuntime.assistant.messages.push({ role: 'USER', content: question });
  liveRuntime.assistant.messages.push({ role: 'ASSISTANT', content: '正在等待大模型响应…' });
  render();
  let retries = 0;
  const timer = setInterval(async function() {
    retries += 1;
    if (!liveRuntime.assistant.conversation) return;
    try {
      const data = await api('/assistant/conversations/' + liveRuntime.assistant.conversation.id + '/messages?page_size=50');
      if (data.items.length) {
        liveRuntime.assistant.messages = data.items.filter(function(item) { return !item.hidden; }).reverse();
        if (state.page === 'digital-human') render();
        if (liveRuntime.assistant.messages.some(function(item) { return item.role === 'ASSISTANT'; })) clearInterval(timer);
      }
    } catch (_) {}
    if (retries >= 15) clearInterval(timer);
  }, 2000);
}, true);
const oldRender=render; render=function(){oldRender();if(['digital-human','communications','llm-settings'].includes(state.page))setTimeout(loadExtras,0);};
