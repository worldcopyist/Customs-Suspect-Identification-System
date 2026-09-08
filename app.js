const app = document.querySelector('#app');
const state = { page: 'login', user: null, csrf: null };
const apiOrigin = window.location.origin;
const serviceUrl = 'http://127.0.0.1:8000/';
const openedAsLocalFile = window.location.protocol === 'file:';

function esc(value) { return String(value == null ? '' : value).replace(/[&<>"]/g, function(char) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char]; }); }
function button(text, cls, action) { return '<button class="btn ' + (cls || '') + '" data-action="' + action + '">' + text + '</button>'; }
function roleLabel(role) { return ({ SUPER_ADMIN: '超级管理员', ADMIN: '管理员', USER: '普通用户' })[role] || '普通用户'; }
function toast(message) { const item = document.querySelector('#toast'); item.textContent = message; item.classList.add('show'); setTimeout(function() { item.classList.remove('show'); }, 2400); }
function idempotencyKey() { return window.crypto && crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(char) { const value = Math.random() * 16 | 0; return (char === 'x' ? value : value & 3 | 8).toString(16); }); }

async function api(path, method, body) {
  if (openedAsLocalFile) throw new Error('当前页面由本地文件打开，无法连接登录服务。请通过 ' + serviceUrl + ' 访问系统。');
  const requestMethod = method || 'GET';
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (requestMethod !== 'GET' && state.csrf) { headers['X-CSRF-Token'] = state.csrf; headers.Origin = apiOrigin; headers['Idempotency-Key'] = idempotencyKey(); }
  const response = await fetch('/api/v1' + path, { method: requestMethod, headers: headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = response.status === 204 ? null : await response.json().catch(function() { return null; });
  if (!response.ok) { const error = new Error((payload && payload.error && payload.error.message) || '请求失败，请稍后重试'); error.code = payload && payload.error && payload.error.code; error.requestId = response.headers.get('X-Request-ID') || (payload && payload.request_id); console.error('[系统请求失败]', { path: path, method: requestMethod, code: error.code, requestId: error.requestId }); throw error; }
  return payload && payload.data;
}
async function refreshCsrf() { state.csrf = (await api('/auth/csrf')).csrf_token; }
async function ensureCsrf() { if (!state.csrf) await refreshCsrf(); }
function authError(message) { const item = document.querySelector('#auth-error'); if (item) item.textContent = message || ''; }
function validPassword(password, confirmation, prefix) {
  if (password.length < 8) throw new Error((prefix || '密码') + '至少需要 8 位字符');
  if (password !== confirmation) throw new Error('两次输入的密码不一致');
}
function validRegistration(username, displayName, password, confirmation) {
  if (!/^[a-zA-Z0-9_]{3,32}$/.test(username)) throw new Error('用户名需为 3–32 位字母、数字或下划线，不能包含空格');
  if (!displayName.trim()) throw new Error('请输入显示名称');
  validPassword(password, confirmation, '密码');
}
function addPasswordVisibilityControls() {
  document.querySelectorAll('input[type="password"]').forEach(function(input) {
    if (input.closest('.password-field')) return;
    const wrapper = document.createElement('span'), toggle = document.createElement('button');
    wrapper.className = 'password-field';
    toggle.type = 'button'; toggle.className = 'password-toggle'; toggle.textContent = '👁'; toggle.title = '显示密码'; toggle.setAttribute('aria-label', '显示密码');
    input.before(wrapper); wrapper.appendChild(input); wrapper.appendChild(toggle);
    toggle.addEventListener('click', function() {
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? '🙈' : '👁';
      toggle.title = visible ? '隐藏密码' : '显示密码';
      toggle.setAttribute('aria-label', toggle.title);
    });
  });
}
function login() {
  const register = state.page === 'register', change = state.page === 'change';
  const title = register ? '创建账户' : change ? '修改初始密码' : '欢迎登录';
  const sub = register ? '注册后将获得基础业务功能权限' : change ? '为保护账户安全，请设置新密码' : '使用账户进入视觉业务工作台';
  let fields = '';
  if (register) fields = '<label>用户名<input name="username" placeholder="3–32 位字母、数字或下划线"></label><label>显示名称<input name="display_name" placeholder="请输入显示名称"></label><label>密码<input name="password" type="password" placeholder="至少 8 位密码"></label><label>确认密码<input name="password_confirm" type="password" placeholder="再次输入密码"></label>';
  else if (change) fields = '<label>当前密码<input name="current_password" type="password" autofocus></label><label>新密码<input name="new_password" type="password" placeholder="8–128 位，不能使用初始密码"></label><label>确认新密码<input name="new_password_confirm" type="password" placeholder="请再次输入新密码"></label>';
  else fields = '<label>用户名<input name="username" autocomplete="username" placeholder="请输入用户名"></label><label>密码<input name="password" type="password" autocomplete="current-password" placeholder="请输入密码"></label>';
  const localHint = openedAsLocalFile ? '<div class="info-note">当前页面由本地文件打开，登录服务不可用。请访问 <a href="' + serviceUrl + '">' + serviceUrl + '</a></div>' : '';
  const switcher = change ? '' : '<p class="auth-switch">' + (register ? '已有账户？' : '还没有账户？') + ' <a data-page="' + (register ? 'login' : 'register') + '">' + (register ? '返回登录' : '立即注册') + '</a></p>';
  app.innerHTML = '<section class="auth"><div class="auth-visual"><div class="course-chip">企业演示</div><h1>海关场景<br>嫌疑人智能识别系统</h1><p>检测　·　留档　·　人工复核</p></div><div class="auth-panel"><div class="auth-form"><div class="brand-mark">⌜</div><h2>' + title + '</h2><p class="muted">' + sub + '</p>' + localHint + '<div class="form-stack">' + fields + '</div><p id="auth-error" class="danger"></p>' + button(register ? '注册' : change ? '确认修改' : '登录', 'primary', 'auth-submit') + switcher + '<div class="info-note">ⓘ　仅用于企业演示，检测结果需人工复核</div></div></div></section>';
}
async function submitAuth() {
  const get = function(name) { const input = document.querySelector('[name="' + name + '"]'); return input ? input.value : ''; };
  try {
    await ensureCsrf();
    if (state.page === 'register') {
      const username = get('username'), displayName = get('display_name'), password = get('password'), confirmation = get('password_confirm');
      validRegistration(username, displayName, password, confirmation);
      await api('/auth/register', 'POST', { username: username, display_name: displayName, password: password, password_confirm: confirmation });
      state.page = 'login'; render(); toast('注册成功，请使用新账户登录'); return;
    }
    if (state.page === 'change') {
      const password = get('new_password'), confirmation = get('new_password_confirm');
      validPassword(password, confirmation, '新密码');
      await api('/auth/password', 'POST', { current_password: get('current_password'), new_password: password, new_password_confirm: confirmation });
      state.user = null; state.page = 'login'; await refreshCsrf(); render(); toast('密码已修改，请使用新密码登录'); return;
    }
    const result = await api('/auth/login', 'POST', { username: get('username'), password: get('password') });
    state.user = result.user; state.csrf = result.csrf_token; state.page = result.session_phase === 'CHANGE_PASSWORD' ? 'change' : 'dashboard';
    render();
  } catch (error) {
    if (error.code === 'UNAUTHENTICATED' && error.message.includes('CSRF')) {
      state.csrf = null;
      try { await refreshCsrf(); authError('安全令牌已更新，请再次提交。'); return; } catch (_) {}
    }
    authError(error.message);
  }
}
function render() { login(); addPasswordVisibilityControls(); }
document.addEventListener('click', function(event) {
  const page = event.target.closest('[data-page]'), action = event.target.closest('[data-action]');
  if (page) { state.page = page.dataset.page; render(); return; }
  if (action && action.dataset.action === 'auth-submit') submitAuth();
});
async function bootstrap() {
  state.user = null; state.page = 'login';
  try {
    await refreshCsrf();
    state.user = await api('/auth/me');
    state.page = 'dashboard';
  } catch (_) { state.user = null; state.page = 'login'; }
  render();
}
bootstrap();
