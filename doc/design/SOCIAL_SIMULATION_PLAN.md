# 可持续社会仿真环境可行性分析与开发计划

最后更新：2026-06-01

## 1. 上游快照

本轮已将两个参考项目拉取到 `upstream_repos/`：

| 项目 | 本地路径 | 当前快照 | 主要用途 | 许可证 |
| --- | --- | --- | --- | --- |
| google-deepmind/concordia | `upstream_repos/concordia` | `53773eb Add examples for interrupt-driven game master` | 仿真内核、Game Master、agent/environment 组件 | Apache-2.0 |
| a16z-infra/ai-town | `upstream_repos/ai-town` | `2693ed6 don't collect joins` | 可视化小镇、实时地图、角色移动、对话与社交 demo | MIT |

当前项目已经具备 `Letta + mem0 + Graphiti + LightRAG` 的记忆分层原型，核心代码在 `backend/app`，运行栈包含 FastAPI、Postgres、Redis、Neo4j、Qdrant、Letta 和 LightRAG。`upstream_repos/` 仍应作为参考源码和许可证保留目录，不建议让生产运行时直接依赖其中的工作树。

## 2. 可行性结论

该计划可行，但第一版必须明确系统边界：Concordia 做“世界裁判 / 环境引擎”，当前 FastAPI 后端做“持久化、记忆编排、任务调度、API 网关”，前端做“可观察和可干预的小镇 UI”。不要在第一版同时引入 Concordia 引擎、AI Town 的 Convex 后端、Letta agent runtime 三套状态机共同驱动世界，否则状态一致性和调试成本会过高。

推荐第一版路线：

1. 以现有 FastAPI 后端为主工程。
2. 新增 `simulation` 后端模块，使用 PyPI 包 `gdm-concordia` 或受控 adapter 调用 Concordia。
3. 使用 Concordia 的 GM/engine 模式处理自然语言行动、社区规则、随机事件和行动结果。
4. 继续使用现有 `ContextBuilder`、`MemoryWriter`、Letta、mem0、Graphiti、LightRAG 作为数字人的身份、记忆、时间事实和背景资料层。
5. 前端先自研 Phaser 或 React + Canvas/Pixi 小镇视图，对接 FastAPI/WebSocket 状态流；AI Town 作为地图、角色、实时交互和产品形态参考。
6. 只有当明确需要 Convex 的实时数据库、多玩家事务和 AI Town 原生部署模式时，才把 AI Town 作为独立 fork 运行，而不是直接并入当前后端。

关键原因：

- Concordia 与当前后端同为 Python 生态，且支持 Python 3.12，适合嵌入后端 worker。
- AI Town 当前主栈是 TypeScript + Convex + PixiJS，不是 Phaser。它适合作为可视化和互动设计参考，但直接迁入会引入第二套后端、数据库和调度体系。
- Letta 与 Concordia 都能承担“agent 行为生成”的一部分能力。第一版应让 Concordia 负责环境和裁判，让 Letta/记忆层负责人格状态和上下文供给，避免两个系统同时拥有最终行动裁决权。

## 3. 第一版产品边界

第一版目标是一个可持续运行的小镇社会仿真原型：

- 一个世界，支持 6 到 12 个数字人。
- 世界具备地点、时间、天气或公共状态、社区规则。
- 数字人有身份、目标、关系、日程、短期观察、长期记忆和成长记录。
- 仿真可暂停、恢复、单步推进、调速。
- 随机事件可按概率、冷却时间、条件触发。
- 用户可以观察世界、查看事件时间线、插入干预。
- 干预以“输入/事件”进入 GM，不默认直接改数据库状态；管理员级强制操作必须审计。
- 所有关键世界变化写入 `events`，并同步到 Graphiti/mem0/LightRAG 中合适的层。

第一版不做：

- 大规模上百 agent 同场仿真。
- 完整多人在线游戏。
- 复杂物理碰撞和战斗系统。
- 直接复刻 AI Town 的 Convex 后端。
- 未授权真实人物模拟。默认只支持 `fictional_persona`；如复用现有 `authorized_real_persona`，必须保留 `consent_confirmed=true` 边界。

## 4. 目标架构

```text
Browser UI
  React control panels
  Phaser/Pixi town viewport
  WebSocket state stream
        |
FastAPI backend
  /api/worlds
  /api/sim-agents
  /api/interventions
  /api/world-events
        |
Simulation service
  Scheduler / tick loop
  Concordia adapter
  random event scheduler
  rule evaluator
  state snapshotter
        |
Memory orchestration
  Letta core persona / dialogue runtime
  mem0 long-term memories
  Graphiti temporal event graph
  LightRAG background corpus
        |
Storage and infra
  Postgres: canonical state and event log
  Redis: locks, queues, pub/sub
  Neo4j: Graphiti
  Qdrant: vector search
```

### 状态所有权

| 领域 | 第一版所有者 | 说明 |
| --- | --- | --- |
| 世界、地点、角色位置、运行状态 | Postgres + simulation service | canonical state，不交给前端或 LLM 直接修改 |
| 行动合理性和环境结果 | Concordia GM adapter | 接收自然语言 action，输出结构化 outcome |
| agent 身份、个人目标、核心人格 | Persona + Letta | 现有 `personas` 继续复用 |
| 长期事实、偏好、习惯 | mem0 + `memory_records` | 从仿真事件和对话中抽取 |
| 时间线和关系变化 | Graphiti + `events` | 每个仿真事件必须带 `reference_time` |
| 背景知识、世界设定、规章文档 | LightRAG + `documents` | 世界设定、地点描述、社区规则文档化 |
| UI 平滑渲染状态 | 前端本地缓存 | 只做展示和乐观动画，不作为事实源 |

## 5. 后端模块设计

建议新增 `backend/app/simulation/`：

```text
backend/app/simulation/
  concordia_adapter.py
  engine.py
  scheduler.py
  random_events.py
  rulebook.py
  state_projection.py
  intervention_service.py
  prompts.py
```

核心职责：

- `engine.py`：统一世界 tick、行动选择、结果落库和事件发布。
- `concordia_adapter.py`：封装 Concordia prefab、GM、agent action spec、结果解析和错误降级。
- `scheduler.py`：用 Redis lock 保证同一个 world 同一时间只有一个 step 在跑。
- `random_events.py`：按条件、概率、冷却时间生成候选事件，再交给 GM 处理。
- `rulebook.py`：将社区规则转为 GM 可用的约束，也提供规则冲突和违规检测。
- `state_projection.py`：把 canonical state 投影为前端需要的轻量世界状态。
- `intervention_service.py`：校验用户干预，写入审计，作为 GM input 进入下一轮。

## 6. 数据模型扩展

在现有 `backend/app/models/entities.py` 基础上新增或迁移以下表：

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `simulation_worlds` | `id`, `name`, `status`, `clock_time`, `speed`, `seed`, `settings` | 世界运行配置和时钟 |
| `world_locations` | `world_id`, `name`, `kind`, `x`, `y`, `description`, `metadata` | 地图和语义地点 |
| `community_rules` | `world_id`, `title`, `content`, `priority`, `status`, `effective_from`, `metadata` | 社区规则和约束 |
| `sim_agents` | `world_id`, `persona_id`, `name`, `status`, `home_location_id`, `current_location_id`, `goals`, `traits` | 数字人与 Persona 绑定 |
| `agent_states` | `agent_id`, `needs`, `mood`, `plan`, `current_action`, `cooldowns`, `metadata` | 可持续运行时状态 |
| `simulation_actions` | `world_id`, `agent_id`, `action_text`, `status`, `source`, `context`, `result` | agent 或用户输入的行动队列 |
| `simulation_events` | `world_id`, `event_type`, `source`, `reference_time`, `actors`, `location_id`, `payload` | 仿真事件流，可同步到现有 `events` |
| `random_event_templates` | `world_id`, `name`, `trigger`, `probability`, `cooldown`, `severity`, `effect_prompt` | 随机事件模板 |
| `user_interventions` | `world_id`, `actor`, `intervention_type`, `payload`, `status`, `result_event_id` | 用户观察和干预审计 |
| `world_snapshots` | `world_id`, `tick_no`, `clock_time`, `state`, `event_cursor` | 回放、恢复和调试 |

第一版可以先让 `simulation_events` 同步写入现有 `events`，后续再决定是否合并两张表。同步规则是：所有对人格、关系、对话、地点或规则有长期影响的事件，都写入 `events` 并进入 `MemoryWriter` 或新的 `SimulationMemoryWriter`。

## 7. API 和实时流

REST：

```text
POST   /api/worlds
GET    /api/worlds
GET    /api/worlds/{world_id}
POST   /api/worlds/{world_id}/start
POST   /api/worlds/{world_id}/pause
POST   /api/worlds/{world_id}/resume
POST   /api/worlds/{world_id}/step
GET    /api/worlds/{world_id}/state
GET    /api/worlds/{world_id}/events

POST   /api/worlds/{world_id}/agents
PATCH  /api/worlds/{world_id}/agents/{agent_id}
POST   /api/worlds/{world_id}/rules
POST   /api/worlds/{world_id}/random-events
POST   /api/worlds/{world_id}/interventions
```

WebSocket 或 SSE：

```text
GET /api/worlds/{world_id}/stream
```

流事件类型：

- `world_state`: 当前投影状态。
- `agent_moved`: 角色位置变化。
- `conversation_started`: 对话开始。
- `conversation_message`: 对话消息。
- `world_event`: GM 解析后的环境事件。
- `rule_violation`: 规则触发或违规。
- `intervention_result`: 用户干预结果。
- `health`: tick 延迟、队列长度、LLM 调用和降级状态。

## 8. Concordia 集成策略

第一版不建议直接把 Concordia 的完整示例搬进业务代码，而是做一个薄 adapter：

1. 将 `simulation_worlds`、`sim_agents`、`community_rules`、最近事件和地点描述组装成 Concordia GM premise。
2. 每个 step 为候选 agent 构造 observation：
   - 当前地点和可见角色。
   - 最近 N 条世界事件。
   - 相关社区规则。
   - 从 `ContextBuilder` 取回的长期记忆、时间事实和背景资料。
3. 让 agent 产生自然语言行动。实现上可先用 Letta 生成，再用 Concordia GM 裁决；后续可替换为 Concordia agent prefab。
4. 将行动交给 Concordia GM resolution，要求输出结构化 JSON：
   - `accepted`: 是否合理。
   - `summary`: 可展示文本。
   - `state_changes`: 地点、关系、资源、状态变化。
   - `observations`: 给相关 agent 的观察。
   - `memory_writes`: 建议进入长期记忆的事实。
   - `rule_effects`: 规则触发、奖励或惩罚。
5. JSON 解析失败时保留原文结果，落为 `simulation_events.payload.raw_outcome`，并进入人工审查或降级规则。

推荐第一版 agent 行动生成方案：

```text
candidate agent selected
  -> build observation and memory context
  -> Letta generates intended action
  -> Concordia GM judges action
  -> structured outcome saved
  -> memory writer persists durable facts
  -> frontend receives projected state
```

这样 Letta 负责“这个人想做什么”，Concordia 负责“世界是否允许以及发生了什么”。

## 9. 记忆与背景层接入

现有分层可以直接复用，但写入粒度需要从“聊天回合”扩展到“仿真事件”。

| 层 | 仿真中的职责 | 写入时机 |
| --- | --- | --- |
| Letta | agent core memory、当前对话和个人目标 | agent 初始化、重要成长事件、用户长期干预 |
| mem0 | 偏好、习惯、关系倾向、稳定事实 | GM outcome 中 `memory_writes` 或对话总结 |
| Graphiti | 谁、何时、何地、做了什么、关系如何变化 | 每个有意义的 `simulation_event` |
| LightRAG | 世界设定、地点背景、历史档案、规则手册 | 导入设定文档、规则版本、世界日志归档 |

需要新增 `SimulationMemoryWriter`：

- 输入：`simulation_event`、相关 agent、GM outcome、reference_time。
- 输出：本地 `events`、Graphiti episode、候选 `memory_records`、必要时 LightRAG 归档文档。
- 要求：所有写入带 `world_id`、`agent_id`、`source_event_id` 和 `reference_time`。

## 10. 前端与 AI Town 取舍

AI Town 提供了非常好的参考：

- 世界、玩家、agent、对话和历史位置的拆分。
- 输入表驱动的 game engine 思路。
- step/tick 分层：高频前端动效，低频后端决策。
- 地图、角色 sprite、对话气泡、冻结/恢复、调试工具。

但第一版不建议直接采用它的 Convex 后端。当前项目已经有 FastAPI、Postgres、Redis 和记忆编排，重复引入 Convex 会造成：

- 两套 canonical state。
- 两套任务调度和事务模型。
- Python Concordia 与 TypeScript Convex action 的跨语言调用复杂化。
- 部署和本地开发门槛明显升高。

前端推荐两条路线：

| 路线 | 适用场景 | 第一版建议 |
| --- | --- | --- |
| 自研 Phaser 小镇 | 当前 FastAPI 后端为主，快速接 WebSocket 状态流 | 推荐 |
| AI Town fork | 需要 Convex 原生实时、多玩家和完整 AI Town demo | 后置 |

自研 Phaser 第一版功能：

- 加载静态 tilemap。
- 展示 agent sprite、姓名、状态、当前行动。
- 对话气泡和事件浮层。
- 右侧观察面板：agent 详情、记忆摘要、关系、事件线。
- 干预面板：添加事件、修改规则、向某个 agent/GM 发送自然语言指令。
- 暂停、恢复、单步、速度控制。

如复用 AI Town 的 assets 或地图工具，需先做素材许可证审计。AI Town 本身是 MIT，但 README 中列出的 tilesheet、UI、sprite 来源各自有授权要求，不能只按 AI Town 仓库许可证处理。

## 11. 可持续运行机制

为了让仿真长期运行，第一版必须加入以下工程机制：

- 单 world 分布式锁：Redis lock，防止并发 step。
- LLM 预算控制：每个 world 每小时调用上限、每 agent 冷却时间、低价值 action 跳过。
- tick 和 LLM 解耦：位置/状态投影可以秒级更新，LLM 决策按 30 秒到数分钟执行。
- 快照和恢复：每 N 个 step 保存 `world_snapshots`，启动时从最近快照恢复。
- 可复现随机性：world 级 seed，随机事件保存候选和命中原因。
- 降级策略：LLM 不可用时使用规则脚本维持基础生活循环。
- 观测指标：tick 延迟、队列长度、LLM 错误率、每小时成本、事件写入量、agent 活跃度。
- 自动归档：长日志进入 LightRAG，Postgres 只保留热事件和索引摘要。
- 审计：所有用户干预、规则修改、强制状态变更写入 `audit_logs`。

## 12. 分阶段开发计划

### Phase 0：上游与技术决策，0.5 到 1 天

已完成：

- 拉取 Concordia 和 AI Town 到 `upstream_repos/`。
- 确认 Concordia 适合作为 GM 和环境引擎。
- 确认 AI Town 更适合作为 UI/交互参考，而非第一版后端基座。

待完成：

- 将 `gdm-concordia` 加到 `backend/pyproject.toml` 的 `simulation` extra。
- 决定前端第一版用 Phaser 还是 Pixi。若没有强约束，建议 Phaser，因为用户原始计划已提到自研 Phaser，且当前前端没有 Convex 依赖。

验收：

- 能在本地 import Concordia。
- 有一个最小 smoke test 调用 GM adapter 的 fake/deterministic path。

### Phase 1：文本仿真内核，3 到 5 天

目标：先不做地图动画，完成可暂停、可单步、可持续写事件的文本世界。

任务：

- 新增仿真数据表和 Alembic migration。
- 新增 world CRUD、agent 绑定 Persona、规则和随机事件 CRUD。
- 实现 `SimulationEngine.step(world_id)`：
  - 加载 world state。
  - 选择 1 到 N 个 agent。
  - 构造 observation。
  - 生成 intended action。
  - 产出 simulation event。
  - 写入 snapshot/event。
- 实现无 LLM 的 deterministic fallback，用于测试和服务不可用时维持运行。
- 新增 worker 循环，支持 pause/resume。

验收：

- 创建一个 world、两个 agent、一条规则。
- 连续 step 20 次能产生事件时间线。
- 停止 LLM 配置时仍能跑 fallback。
- 单元测试覆盖 step、随机事件冷却、规则注入、事件落库。

### Phase 2：Concordia GM adapter，5 到 8 天

目标：让 Concordia 成为行动裁判，而不是只做普通聊天。

任务：

- 安装并封装 `gdm-concordia`。
- 选择初始 prefab：优先 `generic` 或 `situated_in_time_and_place` GM。
- 设计 GM prompt 和 JSON outcome schema。
- 将社区规则、地点、近期事件和干预输入拼进 GM context。
- 解析 outcome 并落为 `simulation_events`。
- 失败时保存 raw outcome，并标记 `needs_review`。
- 引入 `SimulationMemoryWriter` 同步写 Graphiti/mem0。

验收：

- agent 尝试不合理行动时，GM 能拒绝或改写结果。
- 随机事件能改变世界状态或 agent 观察。
- 社区规则能影响 GM 裁决。
- 至少 3 条事件能在 Graphiti 中按时间检索到。

### Phase 3：可视化小镇 MVP，5 到 10 天

目标：用户可以观察和干预，而不是只看日志。

任务：

- 在 `frontend/src` 新增 town viewport。
- 选择 Phaser，或在 React 中用 Canvas/Pixi 实现第一版。
- 实现 `/api/worlds/{id}/state` 轮询，随后升级 WebSocket/SSE。
- 展示地图、地点、agent、当前行动、对话气泡。
- 实现暂停/恢复/单步/速度控制。
- 实现干预面板：
  - 向 GM 注入事件。
  - 对某个 agent 发送指令。
  - 添加或禁用社区规则。
  - 触发随机事件模板。

验收：

- 浏览器能看到 agent 在小镇中移动或状态变化。
- 用户干预能在下一轮 step 中影响事件。
- UI 能显示 GM outcome、规则触发、记忆写入摘要。
- 前端 build 通过。

### Phase 4：数字人成长和关系系统，5 到 8 天

目标：让数字人不仅聊天，还能生活、成长、形成关系。

任务：

- 设计 agent needs：精力、社交、工作/学习、娱乐、安全感。
- 设计成长字段：技能、目标进度、关系亲密度、声誉。
- 从 GM outcome 中抽取成长变化。
- 将稳定变化写入 mem0，事件关系写入 Graphiti。
- 增加 agent daily plan：起床、工作、休息、社交、回家。
- 增加关系驱动的行动选择：主动接近、回避、求助、合作。

验收：

- 运行 1 个仿真日后，agent 的计划、关系或需求发生可解释变化。
- 用户查看某个 agent 时能看到“为什么它这么做”的证据链。
- 重要成长事件能在后续行动中被记住。

### Phase 5：长期运行与运营控制，5 到 10 天

目标：让系统能稳定运行一晚或一天，并可诊断。

任务：

- Redis lock 和 per-world scheduler 硬化。
- 增加成本和速率限制。
- 增加 `/api/worlds/{id}/health`。
- 增加快照恢复和世界归档。
- 增加 6 小时和 24 小时 soak test。
- 增加事件压缩和 LightRAG 归档任务。
- 增加管理后台：队列、失败事件、LLM 调用、降级状态。

验收：

- 6 到 12 个 agent 连续运行 6 小时无状态损坏。
- LLM 失败、Graphiti 不可用、LightRAG 不可用时系统可降级。
- 重启 worker 后能从 snapshot 恢复。

## 13. 主要风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 三套 agent/runtime 状态互相冲突 | 行为不可解释，bug 难定位 | 第一版只让 Concordia 裁决环境，Letta 供人格和意图 |
| LLM 成本和延迟过高 | 无法持续运行 | action 冷却、批处理、fallback、预算上限 |
| AI Town 直接并入过重 | 开发周期失控 | 自研轻量前端，AI Town 只做参考 |
| GM 输出非结构化 | 状态无法可靠落库 | JSON schema、解析失败审查、raw outcome 保留 |
| 长期记忆污染 | agent 行为漂移 | `MemoryCandidate` 审核、置信度、来源和冲突处理 |
| 事件量膨胀 | 存储和检索变慢 | 热事件窗口、摘要归档、LightRAG 原文层 |
| 随机事件破坏可复现 | 难调试 | world seed、记录随机候选和命中原因 |
| 真实人物风险 | 合规和伦理问题 | 第一版默认 fictional persona，沿用 consent 边界 |

## 14. 推荐立即执行清单

1. 新建 `backend/app/simulation` 骨架和 `simulation` optional dependency。
2. 添加 `simulation_worlds`、`sim_agents`、`community_rules`、`simulation_events` 四张最小表。
3. 写一个 deterministic `SimulationEngine.step()`，不接 LLM 也能推进。
4. 写 Concordia adapter smoke test，确认本地模型配置能跑通。
5. 做一个文本世界页面或控制台页面，先展示事件流。
6. 再引入 Phaser 小镇视图和 WebSocket 状态流。

第一版成功标准：用户可以创建小镇，启动 6 个数字人，观察他们按规则生活、聊天、响应随机事件，并能通过干预改变后续事件；系统能连续运行数小时，所有重要事件可回放、可检索、可解释。
