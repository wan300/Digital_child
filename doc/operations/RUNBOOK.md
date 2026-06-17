# 运行手册

## 健康检查

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

返回中应包含：

- `database.configured`
- `letta.base_url`
- `lightrag`
- `neo4j.uri`
- `qdrant.url`

## 社会仿真 smoke test

```powershell
cd backend
uv sync --extra test --extra simulation
uv run python -c "import concordia"
uv run pytest tests/test_simulation_*.py
```

最小 API 路径：

1. 直接调用 API。当前本地运行已关闭登录/JWT，不需要 `Authorization` header。
2. `POST /api/worlds` 创建 world。
3. `POST /api/worlds/{id}/locations` 创建至少一个地点。
4. `POST /api/worlds/{id}/agents` 绑定已有 Persona。
5. `POST /api/worlds/{id}/rules` 创建规则。
6. `POST /api/worlds/{id}/step` 单步推进。
7. `GET /api/worlds/{id}/events` 检查事件时间线。

## 常见问题

### Letta 不可用

聊天仍会返回本地降级回答。检查：

```powershell
docker compose -f infra/docker-compose.yml logs letta
```

### LightRAG 检索为空

先确认 `.env` 中 embedding 模型、维度和 API key 已配置。首次导入后不要随意修改 embedding 配置。

### 真实人物人格无法聊天

`authorized_real_persona` 必须设置 `consent_confirmed=true`。这是第一版的硬性边界。

### 记忆没有进入 mem0

如果 `LLM_API_KEY` 为空或 Qdrant 不可用，系统会保留本地 `memory_records`，不会阻断聊天。

### Concordia 不可用

如果没有安装 `simulation` extra、`LLM_API_KEY` 为空，或 OpenAI-compatible endpoint 不可用，仿真 step 会使用 deterministic fallback 继续写入 `simulation_events`。JSON outcome 解析失败时，事件会标记为 `needs_review` 并保留 `payload.raw_outcome`。
