# Human Memory Orchestrator

这是一个按 `Letta + mem0 + Graphiti + LightRAG` 分层实现的人格记忆系统原型。正式代码位于当前根目录下，`upstream_repos/` 只作为 vendoring 来源，运行时不依赖其中代码。

## 功能

- FastAPI 后端：统一管理人格、会话、长期记忆、时间线、文档、审核和评测。
- React 控制台：中文优先的聊天、人格、记忆、时间线、文档和服务状态页面。
- Letta：本地服务形式运行，用作有状态 agent runtime。
- mem0：长期事实、偏好、习惯、目标记忆。
- Graphiti：带时间戳和来源的事件图谱。
- LightRAG：文本资料、日记、访谈、聊天归档的原文检索层。

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

默认管理员账号来自 `.env`：

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-now
```

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

1. 登录控制台。
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
- 第一版不做 OCR、图片、语音、多用户 RBAC、多租户和云部署。
- RAGFlow 暂不进入第一版。
- LightRAG 的 embedding 模型、维度和存储配置应在第一次导入前固定。

更多设计细节见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
