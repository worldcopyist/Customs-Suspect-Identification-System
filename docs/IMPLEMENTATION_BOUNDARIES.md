# 实现边界与模块映射

## 2026-09-08 目标修订说明（CHG-0017，仅文档）

最新目标是 PRD V1.3／技术文档1.2；下表仍是当前实际 V1.2 源码映射。JWT、厂商模型列表自动填充、VISION/ASR/TTS/OMNI、管理员数字人导入替换、database/results 与 detect_log 迁移、截图消息及其余功能补齐都尚未实施，不能用新文档证明现有路由已提供功能。

本轮明确沿用原生 ES Modules；不再要求为符合旧架构而迁移 Vue/Vite。语音／图片外发只在新方案中经过本轮明确确认，当前代码仍仅文本。数字人管理权属于 ADMIN／SUPER_ADMIN，不延伸到 YOLO 权重；提供的 PMX 需受控转换及用途确认，目前未复制或激活。

源码偏差更正：ui/detection.js 的摄像头结果仍硬编码 sus；CHG-0015 的“标签全部同步”不完整，后续应从返回 class_name 展示，不修改旧结果。没有在本轮执行测试、数据迁移、服务重启、资源转换或云端调用；不新增课程交付材料或验收证据工作。

CHG-0018 随后选择性迁入现有 V1.2 的稳定性修复：退出保留 204 空响应，日志／审计中间件安全处理未设置状态码，非流式 `qwen3*` 请求关闭思考模式，并提供只监听回环地址的 Windows 本地启动脚本。未改变 API、权限、数据表或 SQLite 3.51.3 基线；压缩包中的运行时数据库、日志、缓存、旧文档、请求编号移除和无依据温度范围变更均不属于本项目变更。该脚本尚未在 Windows 真机验证。

CHG-0019 已将认证实现改为 JWT HttpOnly Cookie 加服务端 sid／auth_version 复核，且 WebSocket 使用相同令牌校验；新登录与权限敏感变更撤销旧 sid。默认目标路径为 `database/`／`results/`，正常缺库不自动建库，显式脚本才执行迁移／初始化。相机框从后端 `class_name` 显示。语音、多模态、模型发现、聊天截图、PMX 转换、数字人版本和 detect_log 物理迁移仍是待实施契约，不能认为当前 V1.2 路由已支持。

## 既有实现映射（保留其观察日期）

更新于 2026-09-07。实现状态和验证状态必须分开；详细结果见 `V1.2_IMPLEMENTATION.md`，不再把旧演示页面当作后端能力。

| 模块 | 主要实现位置 | 当前状态与边界 |
| --- | --- | --- |
| 认证、个人中心 | `ui/core.js`、`endpoints/auth.py`、`services/security.py` | 双入口、Cookie/CSRF、改密、会话撤销；匿名不进入初始改密页 |
| 用户与人员 | `ui/admin.js`、`endpoints/users.py`、`endpoints/persons.py` | 真实账户权限及人员 CRUD；人员关联由人工确认 |
| 图片与复核 | `ui/detection.js`、`endpoints/records.py`、`services/detection.py` | 单图／批次、受控媒体、水印、复核历史、软删除；当前 `handsome` 单类别 YOLO 已完成加载及合成图调用，精度与实机仍待验收 |
| 摄像头 | `ui/detection.js`、`endpoints/camera.py` | 真实采集入口、暂停恢复、代际失效、冻结帧保存；物理设备待验收 |
| 内部通讯 | `ui/chat.js`、`endpoints/chat.py`、`endpoints/community.py` | 私聊、邀请建群、公共房间确认加入、在线提示；局域网多设备部署待验收 |
| 云端与智能体 | `ui/assistant.js`、`endpoints/assistant.py`、`endpoints/agents.py` | 角色版本冻结、确切文本预览、单次确认发送、受控 SSE；真实厂商调用待验收 |
| 数字人 | `ui/avatar.js`、`vendor/three` | 本地自包含 GLB 渲染入口，当前为图片占位；未交付正式 3D 资产，无网页上传入口 |
| 运维与审计 | `ui/admin.js`、`endpoints/system.py`、`endpoints/client_logs.py` | 请求编号、异常、关键操作和安全前端诊断；不采集敏感正文，不支持无限期免维护运行 |
| 管理大屏 | `ui/admin.js`、`endpoints/system.py` | 数据库统计、趋势、5 秒刷新；统计记录和框，不称人数 |

历史方案提出过 Vue 3/Vite；V1.3 已正式改为沿用原生 ES Modules。框架偏差已在设计层解决，但新增功能与 API 仍待实现，不是“所有架构条款均已交付”。

已补上聊天长历史分页、显式厂商能力边界探测、GLB 资源预算检查、业务回答结构及确定性事实区块、逐项引用查看与撤权校验。待补强包括：厂商能力与业务模板真实账号实测、知识解读人工准确性评估、正式 GLB 资产验收、持续日志容量治理，以及并发／崩溃／跨平台验收。不得用占位图、测试桩或健康状态替代这些验收。
