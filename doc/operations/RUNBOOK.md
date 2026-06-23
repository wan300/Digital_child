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

## 儿童多模态观察草稿

本地验证命令：

```powershell
cd backend
uv run pytest tests/test_child_multimodal_api.py tests/test_child_multimodal_observation.py tests/test_child_multimodal_safety.py tests/test_child_growth_mvp.py
```

媒体路径：

- 原始媒体默认写入 `backend/data/media/`。
- 预览和关键帧引用默认写入 `backend/data/media/previews/`。
- 两个目录已加入 `.gitignore`，不得提交媒体文件。

生命周期：

1. 上传图片/视频后创建 `MediaAsset`，文件只作为观察证据。
2. 分析任务生成 `ChildMultimodalObservationDraft`，不会直接创建世界。
3. 操作者审核通过或拒绝后，原始媒体和预览默认删除。
4. 审核通过后调用 convert 只创建普通 `ChildWorldDraft`。
5. 最终仍必须调用现有 `/api/worlds/child-drafts/{draft_id}/confirm` 才创建 `SimulationWorld`。

模型不可用时：

- 如果未配置 `LLM_API_KEY` 或 VLM 请求失败，后端返回确定性的可审核 fallback 草稿。
- fallback 草稿保留证据引用、置信度、unknowns 和音频观察占位，不阻断文本儿童草稿创建。
- 禁止项仍会被策略层拦截，例如人脸识别、身份匹配、声纹识别、诊断、智力判断或外貌/声音人格推断。

清理建议：

- 日常测试后可检查 `backend/data/media/` 是否为空；若有残留，优先通过审核/拒绝流程触发删除。
- 不要手工删除数据库行；需要保留审计记录和删除状态。
- 若手工清理了文件系统残留，应记录对应 `media_assets.id` 和原因，避免审计链断裂。

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

## SiliconFlow Kimi VLM

本地验证儿童多模态观察流程时，可在 `.env` 中使用 SiliconFlow 的 OpenAI-compatible endpoint：

```powershell
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=replace-with-local-key
MULTIMODAL_MODEL_NAME=moonshotai/Kimi-K2.7-Code
```

运行注意：

- 不要提交 `.env` 或 API key。
- 适配器会把图片缩略图和视频关键帧作为 `image_url` data URL 发送，本地文件不需要公开托管。
- 视频会在分析任务阶段按每秒 1 帧抽帧，并按 12 帧一批调用 Kimi；上传阶段只做流式落盘，不执行 ffmpeg。
- 音频会提取为片段并使用 SiliconFlow `FunAudioLLM/SenseVoiceSmall` 转写；429 限流按 10/30/60 秒最多重试 3 次。
- 如果 ffmpeg 不可用或视频不可读，系统保留有界的文本帧/音频证据引用，并降级为可审核的确定性观察草稿。
- 2026-06-18 自检确认 `moonshotai/Kimi-K2.7-Code` 支持远程图片 URL 和 data URL；公开文档示例模型 `zai-org/GLM-4.6V` 在当前本地 key 下返回 `403`。
