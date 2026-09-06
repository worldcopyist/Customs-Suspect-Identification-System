# 实现边界与模块映射

更新于 2026-09-07。实现状态和验证状态必须分开；详细结果见 `V1.2_IMPLEMENTATION.md`，不再把旧演示页面当作后端能力。

| 模块 | 主要实现位置 | 当前状态与边界 |
| --- | --- | --- |
| 认证、个人中心 | `ui/core.js`、`endpoints/auth.py`、`services/security.py` | 双入口、Cookie/CSRF、改密、会话撤销；匿名不进入初始改密页 |
| 用户与人员 | `ui/admin.js`、`endpoints/users.py`、`endpoints/persons.py` | 真实账户权限及人员 CRUD；人员关联由人工确认 |
| 图片与复核 | `ui/detection.js`、`endpoints/records.py`、`services/detection.py` | 单图／批次、受控媒体、水印、复核历史、软删除；实际 YOLO 冒烟通过 |
| 摄像头 | `ui/detection.js`、`endpoints/camera.py` | 真实采集入口、暂停恢复、代际失效、冻结帧保存；物理设备待验收 |
| 内部通讯 | `ui/chat.js`、`endpoints/chat.py`、`endpoints/community.py` | 私聊、邀请建群、公共房间确认加入、在线提示；局域网多设备部署待验收 |
| 云端与智能体 | `ui/assistant.js`、`endpoints/assistant.py`、`endpoints/agents.py` | 角色版本冻结、确切文本预览、单次确认发送、受控 SSE；真实厂商调用待验收 |
| 数字人 | `ui/avatar.js`、`vendor/three` | 本地自包含 GLB 渲染入口，当前为图片占位；未交付正式 3D 资产，无网页上传入口 |
| 运维与审计 | `ui/admin.js`、`endpoints/system.py`、`endpoints/client_logs.py` | 请求编号、异常、关键操作和安全前端诊断；不采集敏感正文，不支持无限期免维护运行 |
| 管理大屏 | `ui/admin.js`、`endpoints/system.py` | 数据库统计、趋势、5 秒刷新；统计记录和框，不称人数 |

前端保留原生 ES Modules，没有迁移为技术架构方案提出的 Vue 3/Vite。因此当前是功能迭代，不是“所有架构条款均已交付”。

已补上聊天长历史分页、显式厂商能力边界探测、GLB 资源预算检查、业务回答结构及确定性事实区块、逐项引用查看与撤权校验。待补强包括：厂商能力与业务模板真实账号实测、知识解读人工准确性评估、正式 GLB 资产验收、持续日志容量治理，以及并发／崩溃／跨平台验收。不得用占位图、测试桩或健康状态替代这些验收。
