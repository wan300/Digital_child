# Tasks: 多模态儿童观察草稿

**Input**: `specs/001-child-multimodal-observation/`
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/api.md`, `quickstart.md`
**Generated**: 2026-06-18

## Format

Each task uses the required Spec Kit checklist format:

```text
CHECKBOX T### [P?] [US?] Description with file path
```

`[P]` means the task is parallelizable after its phase prerequisites are complete.
`[US#]` maps to a user story from `spec.md`.

## Phase 1: Setup

**Purpose**: Add shared project configuration and routing placeholders needed before story work.

- [X] T001 Add multimodal media settings for media directory, preview directory, job batch size, model name, request timeout, audio analysis flag, and target confidence thresholds in `backend/app/core/config.py`
- [X] T002 Add media preprocessing dependencies for image metadata/thumbnail generation, video frame extraction, and optional audio metadata/transcription support in `backend/pyproject.toml`
- [X] T003 Add `backend/data/media/` and `backend/data/media/previews/` ignore coverage in `.gitignore`
- [X] T004 Create child observation route module scaffold in `backend/app/api/routes/child_observations.py`
- [X] T005 Register the child observation router in `backend/app/api/router.py`
- [X] T006 [P] Create multimodal prompt/policy constants scaffold in `backend/app/simulation/multimodal_prompts.py`
- [X] T007 [P] Create media storage service scaffold in `backend/app/services/media_storage.py`
- [X] T008 [P] Create media preprocessing service scaffold in `backend/app/services/media_preprocessor.py`
- [X] T009 [P] Create vision model adapter scaffold in `backend/app/services/vision_model.py`

## Phase 2: Foundational

**Purpose**: Establish persistence, schemas, and shared service boundaries used by all user stories. These tasks block US1-US4.

- [X] T010 Add `MediaAsset`, `MediaAnalysisJob`, `ChildMultimodalObservationDraft`, and `ObservationReviewDecision` SQLAlchemy models in `backend/app/models/entities.py`
- [X] T011 Create Alembic migration for media assets, analysis jobs, observation drafts, generated/accepted descriptions, legacy review decisions, indexes, and foreign keys in `backend/alembic/versions/20260618_0003_child_multimodal_observation.py`
- [X] T012 Add request/response schemas for media assets, analysis jobs, observation drafts, generated/accepted child descriptions, review compatibility, authorization confirmation, and conversion in `backend/app/schemas/api.py`
- [X] T013 Add frontend types for media assets, analysis jobs, observation drafts, generated/accepted child descriptions, review compatibility, asset states, and authorization confirmation in `frontend/src/types.ts`
- [X] T014 Add frontend API client methods for `/worlds/child-observations` media, analysis jobs, drafts, accept-description, review compatibility, convert compatibility, reject, and delete in `frontend/src/api.ts`
- [X] T015 [P] Implement filesystem-safe media path generation, sha256 calculation, metadata persistence helpers, and raw deletion state in `backend/app/services/media_storage.py`
- [X] T016 [P] Implement image/video type detection, thumbnail/key-frame/audio evidence reference shape, temporary preview retention, and unreadable-media failure mapping in `backend/app/services/media_preprocessor.py`
- [X] T017 [P] Implement strict observation JSON parsing helpers and model failure normalization in `backend/app/services/vision_model.py`
- [X] T018 Implement `ChildMultimodalObservationService` scaffold and lifecycle method signatures in `backend/app/simulation/multimodal_observation.py`

## Phase 3: User Story 1 - 使用媒体补充儿童初始化草稿 (Priority: P1)

**Goal**: Operator uploads images/video clips with structured child setup fields and receives a generated final child description without creating a child world.

**Independent Test**: A compliant image or video plus structured fields creates a media asset, bounded analysis job, and observation draft with `generated_child_description`, risk flags, media contribution state, and no child world.

### Tests

- [X] T019 [P] [US1] Add API tests for media upload success, unsupported file rejection, empty upload rejection, and no direct world creation in `backend/tests/test_child_multimodal_api.py`
- [X] T020 [P] [US1] Add service tests for analysis job asset states, partial analysis, model failure, audio evidence retention, and evidence/confidence normalization in `backend/tests/test_child_multimodal_observation.py`
- [X] T021 [P] [US1] Add regression test proving existing text-only child draft creation still works in `backend/tests/test_child_growth_mvp.py`

### Implementation

- [X] T022 [US1] Implement `POST /api/worlds/child-observations/media` upload handling in `backend/app/api/routes/child_observations.py`
- [X] T023 [US1] Persist uploaded `MediaAsset` records and raw file metadata in `backend/app/simulation/multimodal_observation.py`
- [X] T024 [US1] Implement image sanitization, metadata extraction, and preview reference generation in `backend/app/services/media_preprocessor.py`
- [X] T025 [US1] Implement bounded video frame extraction, optional audio evidence extraction/transcription metadata, and pending/skipped/excluded state assignment in `backend/app/services/media_preprocessor.py`
- [X] T026 [US1] Implement `POST /api/worlds/child-observations/analysis-jobs` analysis job creation in `backend/app/api/routes/child_observations.py`
- [X] T027 [US1] Implement VLM request construction using existing LLM settings and multimodal policy prompts in `backend/app/services/vision_model.py`
- [X] T028 [US1] Normalize VLM output into observation draft fields with `generated_child_description`, retained internal provenance, confidence values, and unknowns in `backend/app/simulation/multimodal_observation.py`
- [X] T029 [US1] Implement `GET /api/worlds/child-observations/analysis-jobs/{job_id}` status response in `backend/app/api/routes/child_observations.py`
- [X] T030 [US1] Add media upload controls, upload progress, and analysis trigger state to the child draft panel in `frontend/src/components/ObserverConsole.tsx`
- [X] T031 [US1] Render analyzed/pending/skipped/excluded media contribution states in `frontend/src/components/ObserverConsole.tsx`
- [X] T032 [US1] Add user-facing error states for unreadable media, model failure, partial analysis, and text-only fallback in `frontend/src/components/ObserverConsole.tsx`

## Phase 4: User Story 2 - 确认并修正最终儿童描述 (Priority: P1)

**Goal**: Operator reviews one media-derived final child description, edits or rejects it, and approves only safe content for downstream child draft generation.

**Independent Test**: A generated observation draft returns `generated_child_description`; without per-item review, the operator can confirm or edit it through `accept-description`, raw media/previews are deleted, and the accepted description can populate the existing child draft template.

### Tests

- [X] T033 [P] [US2] Add backend tests for generated description acceptance, edited accepted description persistence, and raw media/preview deletion in `backend/tests/test_child_multimodal_api.py`
- [X] T034 [P] [US2] Add backend tests for target-child suggestion storage and low-confidence scene-only generated-description fallback in `backend/tests/test_child_multimodal_observation.py`

### Implementation

- [X] T035 [US2] Implement observation draft retrieval endpoint `GET /api/worlds/child-observations/drafts/{draft_id}` in `backend/app/api/routes/child_observations.py`
- [X] T036 [US2] Implement generated/accepted child-description validation and persistence in `backend/app/simulation/multimodal_observation.py`
- [X] T037 [US2] Implement `POST /api/worlds/child-observations/drafts/{draft_id}/accept-description` in `backend/app/api/routes/child_observations.py`
- [X] T038 [US2] Retain legacy `/review` validation and target-child metadata for compatibility in `backend/app/simulation/multimodal_observation.py`
- [X] T039 [US2] Ensure low target confidence removes target-specific generated description content and keeps only scene/interaction information in `backend/app/simulation/multimodal_observation.py`
- [X] T040 [US2] Add generated child-description confirmation UI with editable textarea and whole-draft risk display in `frontend/src/components/ObserverConsole.tsx`
- [X] T041 [US2] Remove default-path per-item approve/edit/reject/downgrade controls from `frontend/src/components/ObserverConsole.tsx`
- [X] T042 [US2] Remove default-path target-child checkbox/correction controls while keeping backend target confidence metadata in `frontend/src/components/ObserverConsole.tsx`
- [X] T043 [US2] Update child draft panel copy to distinguish generated description, accepted description, and final child-world draft confirmation in `frontend/src/components/ObserverConsole.tsx`
- [X] T044 [US2] Add compact responsive styles for generated description confirmation and risk authorization states in `frontend/src/styles.css`

## Phase 5: User Story 3 - 阻止高风险媒体和不当推断 (Priority: P1)

**Goal**: System blocks prohibited claims, flags high-risk content, allows scoped additional authorization when retained in the final description, and deletes raw media after confirmation or rejection.

**Independent Test**: Real identifiers, school/address data, medical records, trauma content, face recognition, diagnosis, intelligence judgment, and appearance-based personality claims are blocked or scoped through authorization without entering final content.

### Tests

- [X] T045 [P] [US3] Add safety tests for real identifiers, school labels, address patterns, certificates, medical records, violence, trauma, abuse, self-harm, and severe illness in `backend/tests/test_child_multimodal_safety.py`
- [X] T046 [P] [US3] Add safety tests for prohibited face recognition, identity matching, diagnosis, intelligence judgment, and appearance-based personality inference in `backend/tests/test_child_multimodal_safety.py`
- [X] T047 [P] [US3] Add tests for additional authorization scope, rationale, prohibited-claim hard blocks, and audit payloads in `backend/tests/test_child_multimodal_safety.py`
- [X] T048 [P] [US3] Add tests for raw media deletion after final-description confirmation and rejection in `backend/tests/test_child_multimodal_api.py`

### Implementation

- [X] T049 [US3] Implement child media safety policy and prohibited-claim filters in `backend/app/simulation/multimodal_observation.py`
- [X] T050 [US3] Implement audio-derived observation gating and remove dedicated visible-text/OCR privacy-risk detection from the MVP path in `backend/app/simulation/multimodal_observation.py`
- [X] T051 [US3] Implement additional authorization schema validation and scope checks in `backend/app/schemas/api.py`
- [X] T052 [US3] Implement high-risk continuation checks that still block prohibited identity, diagnosis, intelligence, and appearance-based claims in `backend/app/simulation/multimodal_observation.py`
- [X] T053 [US3] Add audit logging for upload, analysis, generated-description confirmation, authorization, rejection, conversion compatibility, and deletion lifecycle events in `backend/app/simulation/multimodal_observation.py`
- [X] T054 [US3] Implement `POST /api/worlds/child-observations/drafts/{draft_id}/reject` with default raw-media deletion in `backend/app/api/routes/child_observations.py`
- [X] T055 [US3] Implement `DELETE /api/worlds/child-observations/media/{asset_id}` raw-media deletion endpoint in `backend/app/api/routes/child_observations.py`
- [X] T056 [US3] Add whole-draft risk flag display, high-risk authorization form, scoped rationale capture, and prohibited-claim warnings in `frontend/src/components/ObserverConsole.tsx`
- [X] T057 [US3] Add raw-media and preview deleted/retained status display after description confirmation or rejection in `frontend/src/components/ObserverConsole.tsx`

## Phase 6: User Story 4 - 确认后复用儿童世界草稿链路 (Priority: P2)

**Goal**: Accepted media-derived child descriptions feed the existing child world draft review flow, and final world creation still uses `ChildWorldDraftService.confirm_draft()`.

**Independent Test**: A `ChildWorldDraftRequest` with `source_observation_draft_id` creates a normal `ChildWorldDraft` only after the source description is accepted; final confirmation remains separate, cancellation creates no world, and the source observation draft is auditable.

### Tests

- [X] T058 [P] [US4] Add tests proving accepted media descriptions can create `ChildWorldDraft` records through `source_observation_draft_id` but not `SimulationWorld` records in `backend/tests/test_child_multimodal_api.py`
- [X] T059 [P] [US4] Add compatibility conversion tests for legacy approved observations, alias/custom display name, approved memory candidates, and risk flag carryover in `backend/tests/test_child_multimodal_observation.py`
- [X] T060 [P] [US4] Add regression tests for final child world confirmation from converted drafts in `backend/tests/test_child_growth_mvp.py`

### Implementation

- [X] T061 [US4] Add optional `source_observation_draft_id` to `ChildWorldDraftRequest` and validate accepted description before child draft creation in `backend/app/schemas/api.py`
- [X] T062 [US4] Retain legacy `POST /api/worlds/child-observations/drafts/{draft_id}/convert` compatibility in `backend/app/api/routes/child_observations.py`
- [X] T063 [US4] Link source observation drafts to `ChildWorldDraft.id` through `ChildMultimodalObservationDraft.child_world_draft_id` without bypassing final confirmation in `backend/app/api/routes/simulation.py`
- [X] T064 [US4] Include observation provenance and risk summary in `ChildWorldDraft.input_params` and `natural_language_prompt` when a source draft is provided in `backend/app/api/routes/simulation.py`
- [X] T065 [US4] Fill the existing child draft template from the accepted generated description instead of auto-selecting a converted draft in `frontend/src/components/ObserverConsole.tsx`
- [X] T066 [US4] Preserve existing final draft preview for `persona_block`, `traits`, `needs`, `development`, `initial_memories`, NPCs, scenes, relationships, and risk flags in `frontend/src/components/ObserverConsole.tsx`
- [X] T067 [US4] Add cancellation/non-creation UI state for approved observation drafts not yet converted or not yet finally confirmed in `frontend/src/components/ObserverConsole.tsx`

## Phase 7: Polish & Cross-Cutting

**Purpose**: Documentation, validation, and regression coverage across all stories.

- [X] T068 [P] Update feature validation instructions with final command names and expected artifacts in `specs/001-child-multimodal-observation/quickstart.md`
- [X] T069 [P] Update API contract examples if implementation response shapes differ in `specs/001-child-multimodal-observation/contracts/api.md`
- [X] T070 [P] Update project documentation to mention controlled media-assisted child observation scope in `doc/README.md`
- [X] T071 [P] Add operation notes for media storage cleanup, deletion audit, and VLM failure recovery in `doc/operations/RUNBOOK.md`
- [X] T072 Run backend focused tests and record results in `specs/001-child-multimodal-observation/quickstart.md`
- [X] T073 Run frontend lint/build and record UI validation notes in `specs/001-child-multimodal-observation/quickstart.md`
- [X] T074 Perform browser review of desktop/mobile child draft panel states and update any layout fixes in `frontend/src/styles.css`
- [X] T075 Review `specs/001-child-multimodal-observation/checklists/safety-review.md` and address any remaining requirement-quality gaps in `specs/001-child-multimodal-observation/spec.md`

## Dependencies

### Phase Dependencies

- Phase 1 Setup must complete before Phase 2 Foundational.
- Phase 2 Foundational must complete before any user story phase.
- US1 provides media upload, analysis jobs, and observation draft creation needed by US2 and US3.
- US2 provides the accepted child description needed by US4 child draft creation.
- US3 can be developed in parallel with US2 after US1 service boundaries exist, but must pass before any release.
- US4 depends on accepted child descriptions from US2 and safety gates from US3.
- Polish depends on all user stories.

### User Story Completion Order

```text
Setup -> Foundation -> US1 -> US2 -> US3 -> US4 -> Polish
                         \       /
                          +-----+
```

US2 and US3 may overlap after US1 data/service contracts are stable. US4 should wait for both.

## Parallel Execution Examples

### Setup / Foundation

```text
T006, T007, T008, T009 can run in parallel after T001-T005.
T015, T016, T017 can run in parallel after T010-T014.
```

### User Story 1

```text
T019, T020, T021 can run in parallel.
T024 and T025 can run in parallel after T023.
T030, T031, T032 can run in parallel after frontend types/API are updated.
```

### User Story 2

```text
T033 and T034 can run in parallel.
T040, T041, T042, T043, T044 can run in parallel after T037-T039 define response shapes.
```

### User Story 3

```text
T045, T046, T047, T048 can run in parallel.
T049, T050, T051 can run in parallel after foundational schemas exist.
T056 and T057 can run in parallel after risk/review responses are stable.
```

### User Story 4

```text
T058, T059, T060 can run in parallel.
T065, T066, T067 can run in parallel after T062 response shape is stable.
```

## Implementation Strategy

### Safe MVP

For this feature, the safe MVP is not US1 alone. Because child media is high sensitivity,
the minimum releasable scope is:

1. Phase 1 Setup
2. Phase 2 Foundational
3. US1 media-assisted observation draft creation
4. US2 human final-description confirmation
5. US3 safety, authorization, and deletion gates

US4 can follow once the accepted-description path is safe, but final product value requires
US4 before users can create a child growth world from media.

### Incremental Delivery

1. Build storage, schemas, and service boundaries.
2. Implement upload + analysis draft creation with mock/fallback VLM responses that produce a final generated child description.
3. Implement description confirmation and safety gates before enabling child draft creation from media.
4. Implement accepted-description handoff to the existing child world draft flow.
5. Validate UI states and raw-media deletion behavior end to end.

## Validation Checklist

- All tasks use `- [ ] T###` format.
- User story tasks include `[US#]` labels.
- Parallel tasks are marked `[P]`.
- Each task includes at least one file path.
- Each user story has independent test criteria.
- Existing text-only child draft creation remains covered.
