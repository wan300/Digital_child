# Implementation Plan: 多模态儿童观察草稿

**Branch**: N/A - Spec Kit branch hook is not configured
**Spec**: `specs/001-child-multimodal-observation/spec.md`
**Date**: 2026-06-18
**Status**: Draft plan ready for task generation

## Summary

Add a media-assisted child creation path that introduces a
`ChildMultimodalObservationDraft` layer before the existing child world draft
confirmation flow. Uploaded images and video clips are temporary observation evidence.
They are analyzed into conservative structured provenance and one generated Simplified
Chinese child description. The operator confirms or edits that final description, which
then fills the existing child-world draft template. Raw media is deleted by default
after description confirmation or rejection.

## Technical Context

**Runtime**: Python 3.12 FastAPI backend, SQLAlchemy async models, Alembic migrations,
React 19 + TypeScript + Vite frontend.

**Existing child creation path**:

- Request schema: `ChildWorldDraftRequest`
- Data table: `child_world_drafts`
- Service: `ChildWorldDraftService.create_draft()` and `confirm_draft()`
- UI entry: observer child draft panel in `frontend/src/components/ObserverConsole.tsx`

**New feature placement**:

- Backend: add a `multimodal_observation` service boundary under child simulation.
- Persistence: add media asset, analysis job, observation draft, generated/accepted
  description fields, and legacy review decision tables; keep raw files outside database.
- API surface: add endpoints under `/api/worlds/child-observations`.
- Frontend: extend the existing child draft panel with media upload, analysis status,
  generated-description confirmation, authorization capture, and handoff into the
  existing draft review.

**Storage**:

- Raw files: local `backend/data/media` in MVP, with an abstraction that can be replaced
  by object storage later.
- Database: metadata, analysis state, generated/accepted descriptions, legacy review
  decisions, risk flags, retained low-sensitivity provenance, and audit records only.
- Raw media deletion: default after final-description confirmation or rejection.

**External services**:

- Vision-capable LLM or VLM adapter for structured observation JSON.
- Video preprocessing with bounded frame extraction.
- Optional audio transcription from submitted video may be summarized into the generated
  child description when configured; voiceprint identity matching and biometric voice
  analysis are out of scope.

**Performance constraints**:

- Product does not impose a fixed upload count or video duration cap.
- Each analysis attempt is bounded by batching, queueing, partial analysis, degradation,
  and explicit analyzed/pending/skipped/excluded states.

**No unresolved clarifications**:

- Raw media default deletion: confirmed.
- Multi-child target suggestion: confirmed.
- High-risk continuation through additional authorization: confirmed.
- Authorized real-child observation with alias/custom display name: confirmed.
- No fixed product-level media cap with bounded processing: confirmed.
- Dedicated visible-text/OCR privacy-risk detection is not required for the current
  non-public validation scope.
- Original media and generated previews are both deleted by default after description confirmation or rejection.
- Target-child confidence bands are fixed as high `>= 0.80`, medium `0.50` to `< 0.80`,
  and low `< 0.50`.
- Audio content from video may be analyzed and summarized into the final editable child
  description, while voiceprint identity matching remains prohibited.

## Constitution Check

### Gate: Layered Code Quality

**Pass.** The plan adds an observation-draft layer and keeps media analysis behind
service/adapters. It does not let VLM output create personas, memory, or worlds directly.
The existing child world draft service remains the single final creation path.

### Gate: Behavior-First Testing

**Pass.** The plan identifies backend tests for safety classification, description
confirmation state transitions, media deletion, high-risk authorization, and child draft
handoff; frontend verification covers generated-description states and non-overlapping
Chinese-first UI.

### Gate: Bounded Performance

**Pass.** Although product scope allows unbounded submitted media, processing is bounded
per attempt through job batching, partial states, and queue/degradation behavior.

### Gate: Privacy, Consent, and Auditability

**Pass.** Raw media is temporary, default-deleted after final-description confirmation
or rejection, and all upload, analysis, generated-description, authorization, handoff,
and deletion actions are auditable. Prohibited inferences remain blocked even with
additional authorization.

### Gate: Consistent Operator Experience

**Pass.** The UI extends the existing observer console with compact panels, statuses,
one editable generated child description, and explicit wording for generated,
accepted, and final child-world facts.

## Project Structure

```text
backend/
  app/
    api/routes/
      simulation.py                # Existing route module; add child-observation routes or split if needed
    models/entities.py             # Add media/analysis/observation/review-compatible tables
    schemas/api.py                 # Add request/response schemas
    simulation/
      child_growth.py              # Keep final child world draft path
      multimodal_observation.py    # New observation draft service
      multimodal_prompts.py        # Structured prompt templates and policy text
    services/
      media_storage.py             # Local-file storage abstraction
      media_preprocessor.py        # Image sanitize/thumbnail/video frame/audio workflow
      vision_model.py              # VLM adapter boundary
    tests/
      test_child_multimodal_observation.py
      test_child_multimodal_safety.py
      test_child_multimodal_api.py

frontend/
  src/
    api.ts                         # Add media upload and observation draft methods
    types.ts                       # Add media/analysis/observation/description-confirmation types
    components/ObserverConsole.tsx # Extend child draft panel and description confirmation UI

specs/001-child-multimodal-observation/
  plan.md
  research.md
  data-model.md
  contracts/api.md
  quickstart.md
```

## Phase 0: Research

Completed in `research.md`.

Key decisions:

- Use a new observation-draft layer rather than direct child-world creation.
- Store raw media outside database and default-delete after final-description confirmation or rejection.
- Analyze media into strict JSON with evidence, confidence, unknowns, risk flags, and a generated final child description.
- Use audio content from video as optional context for the generated final child description when configured; do not perform voiceprint identity matching.
- Do not build dedicated visible-text/OCR privacy-risk detection in MVP.
- Allow additional authorization only for retained high-risk final-description content, never prohibited
  inferences.

## Phase 1: Design And Contracts

Completed artifacts:

- `data-model.md`: entities, fields, relationships, state transitions, validation rules.
- `contracts/api.md`: API and UI contracts for upload, job status, accept-description,
  legacy review/convert compatibility, child draft source provenance, and raw-media deletion.
- `quickstart.md`: validation guide for end-to-end manual and automated checks.

## Implementation Strategy

### Backend

1. Add SQLAlchemy models and Alembic migration for media assets, analysis jobs,
   observation drafts, generated/accepted description fields, and legacy review decisions.
2. Add Pydantic schemas for upload responses, analysis job responses, observation draft
   description-confirmation payloads, authorization confirmation, and source provenance
   on child world draft requests.
3. Implement local media storage abstraction with sha256, MIME/type validation, EXIF
   stripping requirement, temporary thumbnail/key-frame references, and deletion
   status.
4. Implement media preprocessing with image sanitization, bounded video frame extraction,
   and optional audio extraction/transcription metadata.
5. Implement VLM adapter returning strict JSON; fallback to failed/partial job state if
   unavailable.
6. Implement `ChildMultimodalObservationService`:
   - create media assets
   - enqueue/run analysis job
   - normalize model output
   - enforce safety policy
   - persist observation draft and generated child description
   - accept or edit the final child description
   - fill `ChildWorldDraftRequest.natural_language_prompt` with accepted descriptions and `source_observation_draft_id`
   - retain legacy review/convert behavior for compatibility
   - delete raw media after confirmation/rejection
7. Integrate audit logging for every lifecycle transition.
8. Add tests around state transitions, policy blocks, target-child confidence,
   authorized continuation, raw-media deletion, and child draft handoff.

### Frontend

1. Extend the child draft panel with media attachment controls and upload status.
2. Add analysis job progress states: uploaded, queued, running, partial, completed,
   failed, rejected, media deleted.
3. Add generated-description confirmation UI for:
   - upload/frame extraction/transcription/aggregation progress
   - editable `AI 生成儿童描述`
   - whole-draft risk flags and high-risk authorization capture
   - accepted-description handoff into the existing child-world draft form
4. Preserve current final review for `persona_block`, `traits`, `needs`,
   `development`, `initial_memories`, NPCs, scenes, relationships, and risk flags.

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| VLM over-infers personality or diagnosis | High | Prompt policy, schema categories, blocked prohibited claims, final-description confirmation required |
| Raw child media or previews retained accidentally | High | Default deletion job after description confirmation/rejection, deletion state, audit record, tests |
| Multiple children cause wrong target inference | High | Target confidence metadata and scene-only generated-description fallback |
| Product-level no-cap conflicts with performance | Medium | Bounded processing, partial states, queue/defer behavior |
| High-risk authorization becomes blanket bypass | High | Scope-limited authorization, prohibited inference hard blocks |
| Frontend confirmation becomes too dense | Medium | Show progress plus one editable generated-description field consistent with current UI |

## Testing Strategy

Backend:

- Unit tests for media policy classification and prohibited inference filtering.
- Unit tests for observation draft normalization, generated-description construction,
  and confidence/provenance requirements.
- API tests for upload, job status, accept-description, high-risk authorization,
  source-observation child draft creation, legacy conversion, and deletion.
- Regression tests for existing text-only child draft creation.

Frontend:

- TypeScript build/lint.
- Manual browser verification for upload/generated-description/confirm/error states.
- Screenshot checks for compact confirmation panel at desktop and mobile widths before final
  handoff.

## Post-Design Constitution Check

**Pass.** The design keeps the existing child draft confirmation chain as the final
creation mechanism, adds explicit audit and deletion states, and bounds media processing
despite product-level no fixed media cap. No constitution violations require exception.

## Implementation Decisions For Task Execution

- Background execution mode for MVP: synchronous bounded analysis in the API request,
  with job records exposing queued/running/completed/partial/failed states so it can be
  replaced by a worker later.
- VLM provider: use the existing LLM configuration as the first provider boundary; when
  no multimodal provider is configured, return a deterministic partial/fallback draft
  rather than failing child text-only creation.
- Preview storage: generated thumbnails/key frames live under `backend/data/media/previews`
  and are deleted with the raw media after review. Retained evidence references are
  textual only, such as `asset:<id>#frame-3`, `asset:<id>#audio-1`, or `text:setup`.
- Target-child confidence bands: high `>= 0.80`, medium `0.50` to `< 0.80`, low `< 0.50`.

These decisions close the remaining task-generation open items.
