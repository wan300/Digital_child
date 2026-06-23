# 项目文档

本目录是项目文档的统一入口。除根目录 `README.md` 作为仓库入口页外，项目说明、设计、运维和参考资料均收拢到 `doc/` 下维护。

## 文档导航

- [架构说明](design/ARCHITECTURE.md)
- [社会仿真规划](design/SOCIAL_SIMULATION_PLAN.md)
- [运行手册](operations/RUNBOOK.md)
- [导入格式](reference/IMPORT_FORMATS.md)
- [第三方声明](legal/THIRD_PARTY_NOTICES.md)
- [架构参考 PDF](reference/child_growth_os_architecture_reference_report.pdf)
- [工程原则](../.specify/memory/constitution.md)

## 项目概览

这是一个按 `Letta + mem0 + Graphiti + LightRAG` 分层实现的人格记忆系统原型。正式代码位于当前根目录下，`upstream_repos/` 只作为 vendoring 来源，运行时不依赖其中代码。

## 功能

- FastAPI 后端：统一管理人格、会话、长期记忆、时间线、文档、审核和评测。
- React 控制台：中文优先的聊天、人格、记忆、时间线、文档和服务状态页面。
- Letta：本地服务形式运行，用作有状态 agent runtime。
- mem0：长期事实、偏好、习惯、目标记忆。
- Graphiti：带时间戳和来源的事件图谱。
- LightRAG：文本资料、日记、访谈、聊天归档的原文检索层。
- 儿童成长观察：初始化草稿可受控上传图片/视频作为观察证据，生成多模态观察草稿；审核后再转入现有儿童世界草稿确认链路。视频音频可保留为待审核观察证据，不做声纹或身份识别。

## 本地启动

1. 复制配置：

```powershell
Copy-Item .env.example .env
```

2. 修改 `.env` 中的模型配置：

```text
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=...
CHAT_MODEL=...
MEMORY_MODEL=...
GRAPH_MODEL=...
EMBEDDING_MODEL=...
EMBEDDING_DIM=...
```

3. 启动 Docker 本地栈：

```powershell
docker compose -f infra/docker-compose.yml up --build
```

4. 打开控制台：

```text
http://localhost:8080
```

当前本地运行已关闭登录/JWT。打开控制台即可使用所有功能，后端 API 不再要求 `Authorization` header，运行时统一按管理员权限处理。

## 开发模式

后端：

```powershell
cd backend
uv sync --extra test --extra simulation
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

## 第一轮验证

1. 打开控制台。
2. 创建一个 `fictional_persona`。
3. 点击“初始化”创建 Letta agent。
4. 创建会话并发送：“请记住：我喜欢简洁直接的回答。”
5. 到“记忆”页确认记忆已写入。
6. 再问：“我上次告诉过你什么？”检查上下文证据侧栏。
7. 到“文档”页创建文档库，导入 `.txt/.md/.json/.csv` 文本，再搜索原文。

## 社会仿真 Phase 1-2

后端已提供文本世界仿真内核与 Concordia GM adapter：

- `POST /api/worlds` 创建 world。
- `POST /api/worlds/{id}/locations` 添加地点。
- `POST /api/worlds/{id}/agents` 将现有 Persona 绑定为仿真 agent。
- `POST /api/worlds/{id}/rules` 添加社区规则。
- `POST /api/worlds/{id}/random-events` 添加随机事件模板。
- `POST /api/worlds/{id}/interventions` 注入用户干预。
- `POST /api/worlds/{id}/step` 单步推进，即使 world 处于 paused 也可运行。
- `GET /api/worlds/{id}/state` 与 `GET /api/worlds/{id}/events` 查看投影状态和事件线。

验证：

```powershell
cd backend
uv sync --extra test --extra simulation
uv run python -c "import concordia"
uv run pytest
```

## 重要边界

- 第一版只支持 `fictional_persona` 和 `authorized_real_persona`。
- `authorized_real_persona` 必须设置 `consent_confirmed=true`。
- 第一版不做通用 OCR、多用户 RBAC、多租户和云部署；图片/视频/音频仅在儿童观察草稿链路中作为临时审核证据使用，审核确认或拒绝后默认删除原始媒体和预览。
- RAGFlow 暂不进入第一版。
- LightRAG 的 embedding 模型、维度和存储配置应在第一次导入前固定。

更多设计细节见 [design/ARCHITECTURE.md](design/ARCHITECTURE.md)。
