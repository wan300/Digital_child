# Human Memory Orchestrator

这是一个按 `Letta + mem0 + Graphiti + LightRAG` 分层实现的人格记忆系统原型。

## 仓库结构

- `backend/`：FastAPI 后端与仿真能力。
- `frontend/`：React 控制台。
- `infra/`：Docker 和基础设施配置。
- `doc/`：项目文档统一目录。
- `upstream_repos/`：上游参考快照，仅用于 vendoring 和架构参考。

## 快速开始

1. 复制配置：

```powershell
Copy-Item .env.example .env
```

2. 启动本地栈：

```powershell
docker compose -f infra/docker-compose.yml up --build
```

3. 打开控制台：

```text
http://localhost:8080
```

## 文档入口

- 项目总览：[doc/README.md](doc/README.md)
- 工程原则：[.specify/memory/constitution.md](.specify/memory/constitution.md)
- 架构说明：[doc/design/ARCHITECTURE.md](doc/design/ARCHITECTURE.md)
- 运行手册：[doc/operations/RUNBOOK.md](doc/operations/RUNBOOK.md)
- 导入格式：[doc/reference/IMPORT_FORMATS.md](doc/reference/IMPORT_FORMATS.md)
