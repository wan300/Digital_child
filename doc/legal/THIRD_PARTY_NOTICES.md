# Third Party Notices

本项目保留了以下开源项目作为本地 vendoring 来源或架构参考快照。运行时不依赖 `upstream_repos/` 工作树，但需要保留原始许可证。

## mem0

- Source: `upstream_repos/mem0/mem0`
- Vendored path: `backend/vendor/mem0/mem0`
- License: Apache-2.0
- Local changes: packaging metadata only; core source copied as-is initially.

## Graphiti

- Source: `upstream_repos/graphiti/graphiti_core`
- Vendored path: `backend/vendor/graphiti-core/graphiti_core`
- License: Apache-2.0
- Local changes: packaging metadata only; core source copied as-is initially.

## LightRAG

- Source: `upstream_repos/LightRAG/lightrag`
- Vendored path: `backend/vendor/lightrag-hku/lightrag`
- License: MIT
- Local changes: packaging metadata only; core source copied as-is initially.

## Letta

Letta server is not vendored. The Docker stack installs the official `letta` package at runtime and the backend connects through HTTP/client APIs.

## Concordia

- Source: `upstream_repos/concordia`
- Runtime plan: use the published `gdm-concordia` package or a pinned adapter dependency, not the local upstream worktree.
- License: Apache-2.0
- Local changes: none; source snapshot is kept for architecture reference and license traceability.

## AI Town

- Source: `upstream_repos/ai-town`
- Runtime plan: reference for town visualization, map/agent interaction patterns, and possible future fork; not used by the current runtime.
- License: MIT
- Local changes: none; source snapshot is kept for architecture reference and license traceability.
- Note: AI Town references third-party visual assets with their own license/credit requirements. Audit assets separately before copying them into this project.
