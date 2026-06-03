# 架构说明

## 分层原则

系统的核心原则是记忆分层，而不是把所有检索结果直接塞给模型。

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| Letta | 有状态 agent、persona/human core memory、最终回答 | 大规模文档库、复杂时间线 |
| mem0 | 长期事实、偏好、习惯、目标 | 完整对话、关系图谱 |
| Graphiti | 谁、何时、发生了什么、关系如何变化 | 全文检索 |
| LightRAG | 日记、访谈、聊天归档、背景资料原文检索 | 每轮短期记忆 |
| memory_orchestrator | 检索路由、写入策略、冲突处理、上下文预算 | 模型自由决定记忆治理 |

## 读路径

1. 用户消息进入 `POST /api/conversations/{id}/messages`。
2. `RetrievalRouter` 判断是否需要 mem0、Graphiti、LightRAG。
3. `ContextBuilder` 组装：
   - core persona
   - current human relationship
   - long-term memories
   - temporal facts
   - document evidence
   - conflict notes
4. `LettaClient` 将结构化上下文和用户消息交给 Letta。
5. 如果 Letta 不可用，后端返回可审计的降级回答。

## 写路径

1. 用户消息和 assistant 回复写入 `messages`。
2. 完整回合写入 `events`。
3. `MemoryWriter` 尝试写入 Graphiti episode，强制携带 `reference_time`。
4. `MemoryExtractor` 从用户消息抽取长期记忆候选。
5. `PrivacyFilter` 判断敏感度；普通候选自动 approved，敏感候选进入审核。
6. approved 记忆尝试写入 mem0，同时保留本地 `memory_records` 审计副本。

## 冲突处理

第一版的 `ConflictResolver` 先做轻量冲突提示。优先级：

1. 明确时间戳优先于无时间戳。
2. 近期明确表达优先于早期模糊表达。
3. 多来源一致优先于单来源孤证。
4. 时间问题优先 Graphiti。
5. 当前偏好优先 mem0。
6. 原文依据优先 LightRAG。
7. 核心人格边界优先于检索噪声。

## 运行降级

真实服务不可用时：

- Letta：返回本地可审计回答。
- mem0：使用本地 `memory_records` 召回。
- Graphiti：使用本地 `events` 时间线。
- LightRAG：使用本地 `documents.raw_text` 检索。

这种降级保证开发阶段能完成端到端验证，也避免外部服务配置问题阻断 UI 和 API 测试。
