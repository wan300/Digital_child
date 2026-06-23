# Research: 多模态儿童观察草稿

## Decision: Use an observation draft layer before child-world draft creation

**Rationale**: The existing child creation flow already has a safe `draft -> review ->
confirm -> world` pattern. A separate multimodal observation draft keeps media-derived
signals as auditable analysis provenance, lets the LLM summarize them into a generated
child description, and prevents VLM output from directly creating personas, memories,
agents, or simulation worlds.

**Alternatives considered**:

- Directly extending `ChildWorldDraftRequest` with media fields. Rejected because it
  would mix raw evidence with final child-world creation inputs.
- Letting VLM generate a complete `ChildWorldDraft`. Rejected because it bypasses human
  final-description confirmation and makes provenance weak.

## Decision: Store raw media outside database and delete by default after description confirmation

**Rationale**: Child images and videos are high-sensitivity evidence. Database rows
should contain metadata, risk flags, generated/accepted textual descriptions, audit
records, and deletion state, not binary blobs. Default deletion after final-description
confirmation or rejection matches the clarified requirement and project constitution.

**Alternatives considered**:

- Store raw media as database blobs. Rejected due to privacy, backup retention, and
  operational cost.
- Retain raw media until manually deleted. Rejected by requirement clarification.

## Decision: Use strict JSON observation output plus a generated final child description

**Rationale**: The model output must retain structured visible observations,
hypotheses, unknowns, risk flags, and evidence references for audit and testing, while
also producing one conservative Simplified Chinese child description that ordinary users
can confirm or edit directly.

**Alternatives considered**:

- Free-text model summary only. Rejected because it cannot reliably support provenance,
  low-confidence target suppression, or safety policy checks.
- Exposing per-item review as the default UX. Rejected because the desired flow is for
  the LLM to synthesize the media into a final child description, with the user only
  confirming or editing that description before submitting the existing template.
- Full child persona JSON directly. Rejected because it collapses observation and final
  simulation fact.

## Decision: Include video audio in generated-description synthesis when available

**Rationale**: The current validation scope needs to preserve audio content from uploaded
video. Audio observations or transcripts can add useful interaction context, but they
must be summarized through the final editable description and cannot directly become
child-world facts.

**Alternatives considered**:

- Dropping audio from videos. Rejected by updated requirement.
- Using voice identity or biometric voice matching. Rejected because it is a prohibited
  identity inference.

## Decision: Do not build dedicated visible-text/OCR privacy detection in MVP

**Rationale**: The project is currently non-public and used for validation. The first
implementation should still block prohibited claims and unsafe inferences, but it does
not need a dedicated OCR/visible-text privacy risk detector.

**Alternatives considered**:

- OCR-first privacy scanning. Deferred until the feature is prepared for broader or
  public-facing operation.

## Decision: Record system-suggested target child confidence and suppress low-confidence target claims

**Rationale**: The flow should not make ordinary users resolve frame-level target
selection. The backend may record automatic target suggestion and confidence, but low
confidence or ambiguous multi-child media must produce only scene/interaction-level
final descriptions.

**Alternatives considered**:

- Require manual target selection before analysis. Rejected by user clarification.
- Require target correction controls in the default UI. Rejected because the new default
  path confirms one final child description instead of per-slice observations.
- Generate drafts for all children. Rejected as out of scope for single child-world
  creation.

## Decision: Additional authorization can continue high-risk review, but not prohibited claims

**Rationale**: The user selected additional authorization as the high-risk continuation
path. This must be narrowly scoped: it can permit reviewed low-sensitivity content to
continue, but cannot permit face recognition, identity matching, diagnosis, intelligence
judgment, or appearance-based personality claims.

**Alternatives considered**:

- Hard block all high-risk drafts. Rejected by user clarification.
- Allow administrator override without constraints. Rejected because it undermines the
  privacy and safety constitution.

## Decision: No product-level fixed media cap, but bounded processing is mandatory

**Rationale**: The user selected no fixed product cap. To satisfy the constitution's
performance gate, each analysis attempt must remain bounded and expose partial states:
analyzed, pending, skipped, excluded.

**Alternatives considered**:

- Hard cap of 5 images or 60 seconds of video. Rejected by user clarification.
- Unlimited synchronous analysis. Rejected because it violates bounded performance.

## Decision: Use project-local adapters inspired by upstream references

**Rationale**: RAGFlow is useful as inspiration for media analysis pipelines and vision
model adapters; Concordia is useful for multimodal model wrapper patterns. The project
should not runtime-depend on `upstream_repos/` mutable snapshots.

**Alternatives considered**:

- Vendor upstream modules directly into runtime. Rejected by the constitution's layered
  code quality principle.
- Use LightRAG multimodal document pipeline for MVP. Rejected because it is better suited
  to later document/OCR workflows.
