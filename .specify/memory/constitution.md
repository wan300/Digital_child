<!--
Sync Impact Report
Version change: N/A -> 1.0.0
Modified principles:
- Added: Layered Code Quality
- Added: Behavior-First Testing
- Added: Bounded Performance
- Added: Privacy, Consent, and Auditability
- Added: Consistent Operator Experience
Added sections:
- Core Principles
- Engineering and Delivery Gates
- Governance
Removed sections:
- None
Templates requiring updates:
- pending: .specify/templates/plan-template.md is missing
- pending: .specify/templates/spec-template.md is missing
- pending: .specify/templates/tasks-template.md is missing
- pending: .specify/templates/commands/*.md is missing
Runtime guidance docs:
- updated: README.md
- updated: doc/README.md
Follow-up TODOs:
- TODO(SPEC_KIT_TEMPLATES): Initialize .specify/templates before using plan/spec/tasks commands.
-->

# Human Memory Orchestrator Constitution

## Core Principles

### I. Layered Code Quality

All production code MUST preserve the project's explicit ownership boundaries:
FastAPI owns APIs, persistence, auth, and orchestration; simulation modules own world
state transitions; Letta, mem0, Graphiti, and LightRAG integrations stay behind client
or service adapters; React owns presentation and local UI state only. Shared contracts
MUST be represented as typed Pydantic models or TypeScript types, and schema changes
MUST include migrations or documented compatibility notes. Vendor snapshots and
`upstream_repos/` MAY be used for reference or licensing evidence, but runtime code
MUST NOT depend on mutable upstream working trees.

Rationale: the product combines multiple memory, graph, retrieval, and simulation
systems. Strict boundaries make failures auditable and prevent hidden state ownership
from spreading across the codebase.

### II. Behavior-First Testing

Every behavior change MUST include focused tests at the nearest useful boundary. Backend
changes MUST run through `uv run pytest` for affected service, API, simulation, privacy,
and fallback paths. Simulation tests MUST be deterministic when external LLM or
Concordia services are unavailable. Frontend changes MUST pass `pnpm lint`, and
user-visible workflow changes MUST include either component-level assertions,
screenshot/browser verification, or a documented manual check. A failing or skipped test
MUST NOT be accepted unless the skip names the blocking dependency and the follow-up
owner.

Rationale: memory writes, consent checks, and world events are durable user-facing
behaviors. Tests must prove behavior, not just implementation details.

### III. Bounded Performance

Retrieval, context assembly, simulation steps, and document operations MUST have explicit
bounds. Code MUST avoid unbounded fan-out across Letta, mem0, Graphiti, and LightRAG;
`RetrievalRouter` or an equivalent routing decision MUST decide which layers are queried.
Database reads exposed to APIs MUST be paginated or otherwise bounded. Simulation workers
MUST preserve one active step per world through locking or transaction control. Embedding
model, dimension, and vector-store configuration MUST be fixed before first import for a
document library, and later changes MUST be treated as a migration.

Rationale: this system can multiply latency through LLM calls, vector search, graph
queries, and tick loops. Explicit budgets keep the UI responsive and failures isolated.

### IV. Privacy, Consent, and Auditability

Real-person personas MUST require `consent_confirmed=true` before initialization, chat,
simulation binding, or memory writes. Sensitive memory candidates MUST enter review
instead of automatic approval. Secrets, API keys, tokens, private addresses, and raw
personal identifiers MUST NOT be logged, committed, or sent to third-party services
unless the feature explicitly requires it and the data path is documented. Admin
interventions, forced simulation changes, memory approvals, and external-service
fallbacks MUST leave an auditable record. Local auth-disabled mode MUST remain explicit
in UI and docs, and it MUST NOT be treated as a production security posture.

Rationale: the application stores persona, memory, relationship, and timeline data.
Consent and auditability are product requirements, not optional hardening.

### V. Consistent Operator Experience

The operator console MUST remain Chinese-first, utilitarian, and workflow-oriented.
Screens MUST expose the real operating state: selected persona/world, service health,
auth mode, review status, timeline events, and fallback conditions. UI changes MUST
reuse the existing compact panel, tab, form, icon-button, and status patterns unless a
documented design reason exists. Responsive layouts MUST avoid text overlap, hidden
controls, and card nesting; interactive controls MUST have stable dimensions and visible
disabled, loading, empty, and error states.

Rationale: this is an operational memory and simulation console, not a marketing site.
Consistency lets users inspect, intervene, and recover without guessing where state
lives.

## Engineering and Delivery Gates

- Code quality gate: changed Python code MUST pass Ruff rules configured in
  `backend/pyproject.toml`, and changed TypeScript MUST pass the frontend TypeScript
  build. Exceptions require a documented reason in the change record.
- Test gate: every pull request or local handoff MUST list the tests run and the areas
  intentionally not covered.
- Security gate: changes touching personas, auth, memory review, documents, external
  clients, or simulation interventions MUST include a privacy and auditability check.
- Performance gate: changes adding retrieval calls, LLM calls, background workers,
  websocket/SSE streams, imports, or simulation loops MUST state the bound on work,
  concurrency, and persistence.
- UX gate: user-facing changes MUST keep terminology, navigation, and control behavior
  consistent with the current console, including clear local-auth-disabled messaging.

## Governance

This constitution governs implementation plans, feature specs, task breakdowns, reviews,
and release handoffs for the Human Memory Orchestrator project. When a principle
conflicts with an implementation shortcut, the principle wins unless the maintainer
records a time-boxed exception and a follow-up task.

Amendments require a written change to this file, a Sync Impact Report update, and a
review of affected templates, docs, tests, and runtime guidance. Versioning follows
semantic versioning:

- MAJOR: removes or redefines a core principle or governance requirement.
- MINOR: adds a principle, section, or materially expands compliance requirements.
- PATCH: clarifies wording without changing obligations.

Compliance review MUST happen before merging changes that affect memory, consent,
simulation state, retrieval routing, persistence, auth, or the operator console.
Spec Kit templates are currently absent; before using plan/spec/tasks automation, the
project MUST initialize `.specify/templates` and align those templates with this
constitution.

**Version**: 1.0.0 | **Ratified**: 2026-06-16 | **Last Amended**: 2026-06-16
