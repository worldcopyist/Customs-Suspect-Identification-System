# 海关视觉实训系统后端 · V1.2

FastAPI 同源提供前端页面和 `/api/v1` 接口，SQLite 保存账户、会话、检测、通讯及审计数据。当前前端入口为根目录 `index.html` → `frontend.js` → `ui/`，旧演示脚本不再加载。实现与未验收项见 `docs/V1.2_IMPLEMENTATION.md`。

## 启动现有工作区

在项目根目录执行（已有虚拟环境和本地资产）：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

浏览器打开 `http://127.0.0.1:8000/`，不要双击 HTML。健康接口为 `/api/v1/health/live`；OpenAPI 为 `/api/openapi.json`。保持 **一个 Uvicorn worker**，本地任务协调器共享一个独立 YOLO 推理子进程。

第一次启动空数据库才建立 `admin`，初始密码 `admin123`；先登录再强制改密。重启不会重置已有密码。新版文档要求新密码 12–128 位；旧密码校验值保留，输入不自动去除空格。完整会话绝对期限 8 小时、空闲期限 30 分钟；后台轮询不会无限续期。

## 新环境准备

Python 3.12；当前锁定依赖在 macOS arm64 验证，其他平台需要单独验证二进制轮子及摄像头。

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock
```

随后进入 `backend` 执行 `./scripts/build_sqlite_driver.sh` 编译满足版本基线的 SQLite 驱动，再回项目根目录验证：

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/verify_environment.py
backend/.venv/bin/python -m pip check
npm ci
npm run vendor
npm run check
```

`vendor/three` 是随项目保存的离线运行资产；普通启动不需要 npm 或外部 CDN。首次部署可参考 `.env.example`，但**不要覆盖已运行系统的配置**。相对数据库和媒体路径相对于进程工作目录，迁移部署优先使用绝对路径。

## 局域网安全边界

当前核验服务仅监听 `127.0.0.1:8000`。开发默认密钥不能用于局域网部署。部署前需可信 HTTPS、明确服务域名／地址、精确 `TRUSTED_ORIGINS`、非开发环境与受控防火墙。浏览器摄像头在普通局域网 HTTP 下通常不可用。

`APP_SECRET_KEY` 参与会话及云端密钥保护；已有数据时直接替换可能使会话和已加密 API Key 失效。先备份，制定密钥轮换／重新配置流程，不能只改监听地址就宣布部署完成。服务不提供外部账号通讯、任意私聊审计或模型网页上传。

## 备份、升级与维护

升级前在项目根目录执行（目标必须不存在）：

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/backup_database.py backend/data/backups/before-upgrade.db
```

此脚本通过 SQLite backup API 生成一致性数据库快照并检查完整性，不包含媒体或配置；完整恢复还需匹配的媒体目录、配置及旧版本程序。请用受保护存储备份，勿提交密钥。应用启动运行 Alembic 迁移；V1.2 不支持直接降级迁移，回退需停止服务后恢复匹配快照。

管理员可在“运维与审计”按请求编号定位问题。默认运行文件为 `backend/logs/application.log`，单文件 2 MiB、保留 5 个轮转备份；数据库内保留运维／审计事件。日志不记录密码、密钥、请求正文或内部聊天正文。数据库日志尚未实现自动保留期清理，长期使用需要容量监控与备份策略。

使用 `--no-access-log` 关闭原始 Uvicorn 访问日志；项目自身只记录路由模板而不记录查询参数，避免聊天检索词进入 URL 日志。反向代理也需采用同样的脱敏策略。

## 验证

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
npm run check
```

自动化测试使用临时数据库，不能用真实库跑初始化型 HTTP 冒烟脚本。`scripts/http_smoke.py` 仅适用于 8001 端口全新隔离服务，会创建测试账户并修改该隔离库的初始密码；`scripts/http_inference_smoke.py` 依赖前一步测试账户，会写入合成图检测记录。两者均不得用于当前业务库。

YOLO 权重仅部署维护：`backend/models/suspect-yolo11n-best.pt`，校验摘要由代码固定。输出 `sus` 候选框，不代表人员身份、去重人数或执法结论。真实云端调用需要有效厂商配置并人工确认；测试桩结果不能替代云端验收。
