# Data Model: 多模态儿童观察草稿

## Entity: MediaAsset

Represents one uploaded image or video file used as temporary observation evidence.

**Fields**:

- `id`: UUID string.
- `owner_actor`: operator/admin identifier.
- `original_filename`: original client filename, sanitized for display only.
- `media_type`: `image` or `video`.
- `mime_type`: detected content type.
- `sha256`: content hash for duplicate detection.
- `size_bytes`: uploaded file size.
- `duration_seconds`: video duration when known.
- `width`, `height`: dimensions when known.
- `storage_path`: local storage pointer while raw media is retained.
- `preview_refs`: temporary thumbnails or key-frame references used during analysis
  progress and deleted with raw media after description confirmation or rejection.
- `status`: `uploaded`, `preprocessing`, `ready`, `rejected`, `deleted`, `failed`.
- `privacy_flags`: list of detected privacy or safety concerns.
- `deletion_reason`: `description_accepted`, `rejected`, `operator_requested`, `policy`, or empty.
- `deleted_at`: timestamp once raw media is deleted.
- `metadata`: structured details such as frame count, analyzed ranges, audio track
  presence, optional transcript segment references, or processing notes.
- `created_at`, `updated_at`: timestamps.

**Validation rules**:

- Raw media must not be treated as child-world fact.
- Raw media and generated previews default to deletion after final-description confirmation or
  rejection.
- Deleted assets must not expose raw file paths to the UI.
- Duplicate uploads may reuse `sha256` metadata but must keep separate confirmation/audit state.

## Entity: MediaAnalysisJob

Represents a bounded analysis attempt over one or more media assets.

**Fields**:

- `id`: UUID string.
- `status`: `queued`, `running`, `completed`, `partial`, `failed`, `cancelled`.
- `asset_ids`: media assets submitted for this job.
- `analyzed_asset_ids`: assets included in current output.
- `pending_asset_ids`: assets deferred to later processing.
- `skipped_asset_ids`: assets intentionally not analyzed.
- `excluded_asset_ids`: assets excluded due to policy or unreadable input.
- `target_child`: proposed target descriptor with confidence and evidence references.
- `model_provider`: configured model provider name.
- `model_name`: configured model name.
- `prompt_version`: prompt/policy version identifier.
- `raw_response`: raw model output for audit/debug while safe to retain.
- `normalized_result`: normalized observation JSON.
- `error_message`: user-safe failure explanation.
- `attempt_count`: number of analysis attempts.
- `started_at`, `completed_at`: timestamps.
- `created_at`, `updated_at`: timestamps.

**Validation rules**:

- Each job must expose bounded progress even if the product accepts many files.
- `completed` requires all submitted assets to be analyzed or explicitly skipped/excluded.
- `partial` requires clear analyzed/pending/skipped/excluded states.
- Raw model output must not become final child-world content without final-description confirmation.

## Entity: ChildMultimodalObservationDraft

Observation layer created from structured child setup fields plus media analysis. The
default user-facing artifact is a generated final child description, not a per-item
review checklist.

**Fields**:

- `id`: UUID string.
- `status`: `draft`, `in_review`, `description_accepted`, `approved`, `rejected`, `converted`.
- `analysis_job_id`: source analysis job.
- `child_world_draft_id`: created child world draft after accepted-description handoff or legacy conversion, nullable.
- `structured_setup`: child alias/display name, age, caregiver labels, class context,
  peer count, optional text prompt, seed.
- `target_child`: suggested target child descriptor and confidence; low-confidence cases suppress target-specific generated descriptions.
- `generated_child_description`: model-generated Simplified Chinese paragraph suitable for `natural_language_prompt`.
- `accepted_child_description`: operator-confirmed or edited final child description.
- `observable_summary`: conservative visible-content summary.
- `visible_observations`: list of non-inferential observations.
- `non_identifying_appearance`: abstract appearance notes safe for review.
- `behavior_signals`: observed actions/interactions with evidence and confidence.
- `temperament_hypotheses`: reviewable hypotheses with evidence and confidence.
- `interests`: reviewable interest hypotheses.
- `development_hints`: reviewable hints, not diagnoses.
- `avatar_brief`: non-identifying style brief only.
- `initial_memory_candidates`: draft memories requiring approval.
- `unknowns`: unsupported or ambiguous items.
- `risk_flags`: privacy/safety flags and severity.
- `authorization_confirmation`: optional high-risk continuation confirmation for retained final-description content.
- `approved_payload`: content accepted for `ChildWorldDraftRequest` handoff or legacy conversion.
- `rejected_reason`: operator rejection reason.
- `raw_media_deleted_at`: timestamp when associated raw media deletion completed.
- `created_at`, `updated_at`: timestamps.

**Validation rules**:

- Target-specific generated description content requires sufficient target-child confidence; low-confidence cases only retain scene-level or interaction-level information.
- Low-confidence target cases can only produce scene-level or interaction-level
  observations.
- Prohibited claims are never approved, even with additional authorization.
- Accepted payload must use alias or user-defined display name, not real identifiers.
- Retained evidence references must be textual pointers such as `asset:<id>#frame-3`,
  `asset:<id>#audio-1`, or `text:setup`; they must not retain preview images, raw clips,
  audio files, or reconstructable media excerpts after deletion.
- Accepted-description handoff and legacy conversion must route through the existing child world draft flow.

## Entity: ObservationReviewDecision

Legacy compatibility entity for operator decisions on individual generated statements or
draft sections. The default UX no longer requires ordinary users to create these
records.

**Fields**:

- `id`: UUID string.
- `observation_draft_id`: parent observation draft.
- `item_path`: path to the reviewed item, such as `interests[0]`.
- `decision`: `approved`, `edited`, `rejected`, `downgraded`, `unknown`.
- `original_value`: original generated value.
- `final_value`: retained value after edit or downgrade.
- `confidence`: retained confidence value.
- `evidence_refs`: evidence references retained with final value.
- `rationale`: operator reason when editing, rejecting, downgrading, or authorizing.
- `created_at`, `updated_at`: timestamps.

**Validation rules**:

- Every retained hypothesis, interest, development hint, and initial memory candidate in
  the legacy review path must have an approval decision.
- Rejected items must not appear in the conversion payload.
- Edited items must preserve provenance to original evidence.

## Entity: AuthorizationConfirmation

Structured object stored inside observation draft and audit payload when high-risk
continuation is used.

**Fields**:

- `confirmed`: boolean.
- `confirmed_by`: operator/admin identifier.
- `confirmed_at`: timestamp.
- `authorization_scope`: categories allowed to continue.
- `risk_categories`: detected high-risk categories.
- `operator_rationale`: short reason.
- `retained_content_scope`: what may be retained after review.

**Validation rules**:

- Required for high-risk continuation.
- Does not permit prohibited identity, diagnostic, intelligence, or appearance-based
  personality claims.
- Must be captured before accepted-description handoff or legacy conversion to a child world draft.

## Relationships

- `MediaAnalysisJob` has many `MediaAsset` records.
- `ChildMultimodalObservationDraft` belongs to one `MediaAnalysisJob`.
- `ChildMultimodalObservationDraft` may have many legacy `ObservationReviewDecision` records.
- `ChildMultimodalObservationDraft` may create one `ChildWorldDraft`.
- Existing `AuditLog` records lifecycle events for all new entities.

## State Transitions

### MediaAsset

```text
uploaded -> preprocessing -> ready
uploaded/preprocessing/ready -> rejected
ready/rejected -> deleted
preprocessing -> failed
failed -> deleted
```

### MediaAnalysisJob

```text
queued -> running -> completed
queued -> running -> partial
queued/running -> failed
queued/running/partial -> cancelled
partial -> running -> completed
```

### ChildMultimodalObservationDraft

```text
draft -> in_review -> description_accepted -> converted
draft -> in_review -> approved -> converted (legacy review path)
draft -> in_review -> rejected
draft/in_review -> rejected
description_accepted/approved -> rejected (only before child draft handoff)
```

## Indexes And Constraints

- Index `media_assets.sha256` for duplicate detection.
- Index `media_assets.status`, `media_analysis_jobs.status`, and
  `child_multimodal_observation_drafts.status` for confirmation queues.
- Index `child_multimodal_observation_drafts.child_world_draft_id`.
- Keep JSON payload fields for flexible VLM output, but normalize top-level status,
  ownership, generated/accepted description, risk, and handoff state into explicit columns.
