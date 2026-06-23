# Feature Specification: 多模态儿童观察草稿

**Feature Branch**: N/A - no before_specify hook configured
**Created**: 2026-06-18
**Status**: Draft
**Input**: 用户希望在创建儿童成长模拟时上传图片或视频，由自动多模态分析汇总生成可直接放入模板的儿童描述，经用户确认或编辑该最终描述后复用现有儿童世界草稿确认链路创建模拟数字人。

## Clarifications

### Session 2026-06-18

- Q: 原始图片/视频在确认完成后默认怎么处理？ -> A: 最终儿童描述确认或拒绝后默认删除原始媒体，仅保留已确认文字描述、风险标记、审计记录和必要的低敏分析 provenance。
- Q: 媒体里出现多个儿童时，系统如何确定要创建的目标儿童？ -> A: 系统可以自动建议主角儿童并记录目标置信度；低置信度或无法区分时，最终儿童描述只能保留场景/互动层信息，不能生成目标儿童个体推断。
- Q: 高风险内容被检测到后，管理员是否可以强制覆盖并继续创建？ -> A: 仅在额外确认授权后可以继续；未授权或授权信息不完整时，高风险内容保持阻断。
- Q: 最终创建的儿童数字人应属于哪种身份范围？ -> A: 允许基于授权真实儿童观察创建，但最终使用别名或用户自定义名字，并采用非识别性抽象描述。
- Q: MVP 阶段一次儿童观察草稿允许上传多少媒体？ -> A: 产品层不设固定上传数量或时长上限；系统尽量处理，但必须以分批、排队、降级或提示继续处理的方式保持单次分析有界。

## User Scenarios & Testing

### User Story 1 - 使用媒体补充儿童初始化草稿 (Priority: P1)

作为管理员/观察者，我希望在填写儿童称呼、年龄、照护者、班级等结构化信息时上传图片或视频片段，让系统生成一份基于可观察证据的儿童观察草稿，减少从零描述孩子状态的负担。

**Why this priority**: 这是功能的核心入口。没有媒体输入到最终儿童描述的闭环，后续确认和世界创建都无法成立。

**Independent Test**: 使用一组合规图片或视频片段创建草稿；系统保留必填结构化字段，并生成一段可确认或编辑的中文儿童描述、风险标记和分析 provenance。

**Acceptance Scenarios**:

1. **Given** 管理员填写了儿童年龄、称呼、照护者、班级和同伴数量，**When** 上传合规图片并提交分析，**Then** 系统生成观察草稿，并且不会直接创建儿童世界。
2. **Given** 管理员上传视频片段，**When** 系统完成分析，**Then** 草稿展示跨片段归纳后的最终儿童描述，并标注分析进度与媒体贡献状态。
3. **Given** 媒体无法被分析或质量不足，**When** 管理员查看结果，**Then** 系统展示可理解的失败/不足原因，并允许重新上传或改用文本描述。
4. **Given** 媒体中出现多个儿童，**When** 系统无法高置信地区分目标儿童，**Then** 最终描述仅保留场景/互动层信息，不输出目标儿童特质、发展或记忆结论。
5. **Given** 管理员基于授权真实儿童媒体创建草稿，**When** 提交结构化字段，**Then** 系统要求使用别名或用户自定义名字，并避免真实姓名、真实学校、精确地址或可识别头像进入儿童世界。
6. **Given** 管理员上传大量图片或长视频，**When** 系统无法一次完成全部分析，**Then** 系统分批、排队、降级或提示继续处理，并展示哪些媒体已纳入当前观察草稿。

---

### User Story 2 - 确认并修正最终儿童描述 (Priority: P1)

作为管理员/观察者，我希望在创建儿童世界前看到模型根据媒体汇总生成的最终儿童描述、整体风险提示和即将写入模板的内容，并能编辑、确认或拒绝该描述。

**Why this priority**: 该功能处理儿童媒体与人格模拟，必须由人确认哪些内容可以进入系统，避免误判、过度推断和隐私泄露。

**Independent Test**: 提交一份媒体观察草稿；分析完成后无需逐项审核观察切片，界面显示一段可编辑的最终儿童描述，确认后写入现有 `natural_language_prompt`，且不会直接创建世界。

**Acceptance Scenarios**:

1. **Given** 系统生成了观察草稿，**When** 管理员进入确认界面，**Then** 页面展示上传/抽帧/转写/汇总进度、整体风险标记和一段 `AI 生成儿童描述`，不展示普通用户需要逐条确认的切片观察项。
2. **Given** 最终描述包含需要保留的高风险内容，**When** 管理员确认描述，**Then** 系统要求整体授权确认和操作理由；禁止项仍硬阻断且不能进入最终描述。
3. **Given** 管理员编辑了将写入儿童世界模板的描述，**When** 提交确认，**Then** 系统保存 `accepted_child_description`、删除原始媒体和预览，并把确认后的描述填入现有生成模板。

---

### User Story 3 - 阻止高风险媒体和不当推断 (Priority: P1)

作为系统维护者，我希望媒体分析不能进行身份识别、真实学校/地址提取、诊断、智力判断或根据长相推断性格，并在高风险内容出现时阻止确认创建。

**Why this priority**: 儿童媒体属于高敏感输入。功能必须先建立安全边界，否则不能进入可用状态。

**Independent Test**: 使用包含真实姓名、学校标识、证件、医疗材料、创伤内容或明显身份识别请求的输入；系统必须给出风险提示，并阻止这些内容直接进入儿童世界。

**Acceptance Scenarios**:

1. **Given** 媒体或文本包含真实学校、家庭地址、证件号或医疗诊断，**When** 系统生成草稿，**Then** 草稿被标记为高风险，并且不能直接确认创建。
2. **Given** 用户要求根据脸部识别身份或推断智力/诊断，**When** 系统处理请求，**Then** 系统拒绝该类推断，只保留可观察、非识别性的描述。
3. **Given** 媒体中存在可见文字或标识，**When** 系统检测到潜在隐私风险，**Then** 草稿以风险提示和人工处理建议呈现，而不是把该信息写为儿童事实。
4. **Given** 高风险草稿需要继续处理，**When** 管理员提供额外授权确认，**Then** 系统记录授权确认、风险范围和操作理由，并仅允许已授权范围内的低敏内容进入后续草稿。

---

### User Story 4 - 确认后复用儿童世界草稿链路 (Priority: P2)

作为管理员/观察者，我希望通过确认后的媒体儿童描述继续进入现有的儿童世界草稿流程，确认后再创建可暂停、可观察、可干预的成长模拟世界。

**Why this priority**: 多模态能力应扩展现有草稿链路，而不是新增绕过审核的平行创建路径。

**Independent Test**: 确认媒体生成的儿童描述后，系统使用现有模板生成可确认的儿童世界草稿；确认前可以再次查看将创建的孩子、场景、NPC、关系、初始记忆和风险标记。

**Acceptance Scenarios**:

1. **Given** 管理员确认了媒体生成的儿童描述，**When** 点击现有“生成审核草稿”，**Then** 系统展示 `persona_block`、`traits`、`needs`、`development`、`initial_memories` 和风险标记供最终确认。
2. **Given** 管理员在最终确认前取消，**When** 返回草稿列表，**Then** 已确认的媒体描述保持可追溯状态，但不创建世界。
3. **Given** 管理员最终确认，**When** 创建完成，**Then** 生成的世界来源可追溯到已确认的媒体描述草稿，而不是原始媒体直接写入。

### Edge Cases

- 上传的媒体包含多个儿童时，系统可以建议主角儿童并记录目标置信度；低置信度或无法明确区分时，最终描述只能生成场景/互动观察，不能生成目标儿童个体推断。
- 媒体画面模糊、遮挡严重、光线不足或时长过短。
- 媒体数量或视频时长超过一次分析可处理范围时，系统保持草稿可继续，并清楚标注已分析、待分析和未纳入内容。
- 用户提供的文本字段与媒体观察明显冲突。
- 同一媒体重复上传或用户重复触发分析。
- 媒体中出现成人、其他儿童、学校标识、证件、医疗材料或家庭住址。
- 媒体暗示暴力、创伤、虐待、自伤、重大疾病或违法伤害。
- 高风险内容如果仍保留在最终描述里且未提供额外授权确认时保持阻断；已提供授权时，只允许低敏、非识别性、已确认内容继续进入草稿。
- 自动分析返回空结果、过度自信、不可解析内容或互相矛盾的观察。
- 管理员只想使用文本草稿，不上传任何媒体。
- 描述确认或拒绝后，原始媒体默认被删除；系统仍需保留已确认文字描述、风险标记、审计记录和必要的低敏分析 provenance。

## Requirements

### Functional Requirements

- **FR-001**: The system SHALL allow an authorized operator to attach image files or video clips while creating a child initialization draft.
- **FR-002**: The system SHALL require the operator to provide or confirm structured child setup fields, including age, child alias or user-defined display name, caregiver labels, class context, peer count, and optional text description.
- **FR-003**: The system SHALL treat uploaded media as observation evidence only; media SHALL NOT directly create a child world, persona, memory, or simulation agent.
- **FR-004**: The system SHALL produce an observation draft that retains structured analysis internally and exposes a generated Simplified Chinese child description suitable for `natural_language_prompt`, plus risk flags, unknowns, and media contribution state.
- **FR-005**: The system SHALL attach confidence and evidence references to every hypothesis, interest, development hint, and initial memory candidate derived from media.
- **FR-006**: The system SHALL mark uncertain or unsupported items as unknown instead of presenting them as facts.
- **FR-007**: The system SHALL prohibit face recognition, identity matching, real school/address extraction, medical or psychological diagnosis, intelligence judgment, family-background inference, and personality inference based only on physical appearance.
- **FR-008**: The system SHALL flag high-risk content before confirmation when media or text contains real identifiers, sensitive personal data, school identifiers, medical records, severe harm, abuse, self-harm, or other unsafe child-related content.
- **FR-009**: The system SHALL prevent high-risk drafts from being confirmed unless the risk is resolved, removed, explicitly rejected from the child creation payload, or covered by an additional authorization confirmation.
- **FR-010**: The system SHALL show upload, frame extraction, transcription, aggregation progress, media contribution status, and whole-draft risk flags without requiring ordinary operators to inspect frame slices, evidence refs, or per-item observations.
- **FR-011**: The system SHALL allow the operator to edit, confirm, or reject the single final generated child description before it can affect the child world draft.
- **FR-012**: The system SHALL fill the existing child-world draft request from the accepted child description and existing structured fields, preserving the existing review-then-confirm creation pattern.
- **FR-013**: The system SHALL show the operator the resulting child profile, traits, needs, development hints, initial memories, NPC setup, scene setup, and risk flags before final world creation.
- **FR-014**: The system SHALL keep an audit trail for media submission, analysis completion, final-description generation, accepted-description edits, rejection, confirmation, and raw-media deletion.
- **FR-015**: The system SHALL delete original uploaded media and generated previews by default after the operator confirms or rejects the final description, while retaining accepted textual description, risk flags, audit records, and low-sensitivity analysis provenance that cannot reconstruct the original media.
- **FR-016**: The first release SHALL retain and may analyze audio content from submitted video when available; audio-derived observations or transcripts must be summarized through the final editable child description and SHALL NOT bypass human confirmation or become direct child-world facts.
- **FR-017**: The system SHALL present the generated and accepted child descriptions in Simplified Chinese and use wording that distinguishes observation, hypothesis, and confirmed child-world fact.
- **FR-018**: The system SHALL continue to support text-only child draft creation for users who do not upload media.
- **FR-019**: When media contains multiple children, the system SHALL record proposed target-child confidence and suppress target-specific traits, development hints, or initial memory candidates from the generated final description when confidence is low or the target cannot be distinguished.
- **FR-020**: When target-child confidence is low (`< 0.50`) or the target cannot be distinguished, the system SHALL limit the generated description to scene-level or interaction-level observations and SHALL NOT produce target-specific child profile content from that media; medium confidence (`0.50` to `< 0.80`) may only retain target-specific content when the final accepted description clearly grounds it in non-identifying observable context.
- **FR-021**: When an operator continues from a high-risk final description through additional authorization, the system SHALL record the authorization confirmation, risk category, approved scope, operator rationale, and final retained content.
- **FR-022**: Additional authorization SHALL NOT allow prohibited inferences such as face recognition, diagnosis, intelligence judgment, or personality inference from physical appearance.
- **FR-023**: When a draft is based on authorized real-child observation, the resulting child world SHALL use an alias or user-defined display name and non-identifying abstract description rather than real names, real school identifiers, precise addresses, or identifiable avatars.
- **FR-024**: The system SHALL NOT impose a fixed product-level limit on the number or duration of media attached to a draft, but it SHALL keep each analysis attempt bounded through batching, queuing, partial analysis, degradation, or operator prompts to continue later.
- **FR-025**: When not all submitted media is analyzed, the system SHALL show which media contributed to the current observation draft and which media remains pending, skipped, or excluded.

### Non-Functional Requirements

- The confirmation experience SHALL remain clear for non-technical operators and SHALL NOT require understanding model internals or per-frame evidence schemas.
- Media handling SHALL minimize retained sensitive content and SHALL make raw-media retention status visible.
- Generated output SHALL be conservative: when evidence is weak or ambiguous, the system SHALL prefer scene-level wording, unknown markers, or manual editing over assertive claims.
- The feature SHALL preserve the current age and child-world safety boundaries unless a later approved specification changes them.
- The feature SHALL avoid unlimited synchronous analysis; large media submissions SHALL remain understandable through bounded batches, clear progress, and partial-result states.

### Key Entities

- **Media Submission**: A user-provided image or video clip used as temporary observation evidence, with type, upload status, confirmation status, privacy flags, and retention status.
- **Observation Draft**: A generated analysis record that stores structured observations internally and exposes `generated_child_description`, `accepted_child_description`, risk flags, unknowns, and media contribution state.
- **Observation Evidence Reference**: A low-sensitivity provenance link between internal analysis and the media preview, frame, segment, or user-provided text; ordinary users do not need to review it item by item.
- **Description Confirmation**: The operator's edit, rejection, or final confirmation of the generated child description that may populate `natural_language_prompt`.
- **Child World Draft**: The reviewed child simulation draft that contains child profile, traits, needs, development hints, initial memories, NPCs, scenes, relationships, and risk flags.
- **Audit Record**: A durable record of upload, analysis, generated description, accepted description, rejection, deletion, or blocked confirmation events.

## Success Criteria

- **SC-001**: In usability testing, 90% of operators can create a confirmable generated child description from media and structured fields in under 5 minutes.
- **SC-002**: 100% of media-derived child-world creations require explicit human confirmation of the final child description before final world creation.
- **SC-003**: 0 high-risk drafts containing unresolved real identifiers, school/address data, medical records, severe harm, or identity-recognition requests can be confirmed without recorded additional authorization, risk scope, and operator rationale.
- **SC-004**: At least 95% of generated final descriptions avoid per-slice review language and either summarize observable evidence conservatively or mark weak claims as unknown.
- **SC-005**: In review sampling, at least 90% of accepted retained statements are traceable through internal analysis provenance to visible media evidence or operator-provided structured fields.
- **SC-006**: Text-only child draft creation remains available and can still be completed without uploading media.
- **SC-007**: 100% of confirmed or rejected submissions show that original media was deleted after final-description confirmation or rejection, while accepted textual descriptions and audit records remain accessible.
- **SC-008**: 100% of low-confidence multi-child submissions suppress target-specific statements from the generated final child description unless the accepted description is manually rewritten into non-identifying, observable terms.
- **SC-009**: 100% of authorized real-child observation drafts use an alias or user-defined display name before final world creation.
- **SC-010**: 100% of large media submissions show whether each submitted item was analyzed, pending, skipped, or excluded before the operator confirms the draft.

## Assumptions

- The primary user is an administrator/observer who is authorized to create child simulation drafts.
- The operator is responsible for having guardian authorization or lawful permission to upload child media.
- The system may use authorized real-child observations as input, but it creates an abstracted, reviewed child simulation profile using an alias or user-defined display name, not a directly identifiable digital replica of a real child.
- Additional authorization can permit reviewed continuation from a high-risk draft, but it cannot permit prohibited identity recognition, diagnostic, or appearance-based personality claims.
- The initial scope supports images and video clips as observation evidence, including retained audio tracks where available. Audio transcription may be used when configured, but voiceprint identity matching and biometric voice analysis remain out of scope.
- The product does not define a fixed upload count or duration cap for MVP, but analysis remains bounded through batching and partial-result handling.
- Raw media is temporary review evidence and is deleted by default after confirmation or rejection.
- The current child creation age range and existing draft-confirm-world flow remain the governing path.
- Existing project principles apply: privacy, consent, auditability, bounded performance, behavior-first testing, and consistent Chinese-first operator UX.

## Out of Scope

- Face recognition, identity matching, or matching a child against external datasets.
- Direct creation of a child world from media without a human final-description confirmation step.
- Real child identity cloning through real names, real school identifiers, precise addresses, or highly similar recognizable avatars.
- Medical, psychological, developmental disorder, intelligence, or family-background diagnosis from media.
- Building a photorealistic or identifiable child avatar from uploaded media.
- Long-term storage of raw media as personality memory.
- Unattended bulk media ingestion outside a single confirmed child-draft workflow.
- Voiceprint identification, biometric voice matching, or unconfirmed speech-derived child memory creation.

## Phased Scope

### Phase 1 - MVP

- Media-assisted final child-description generation.
- Confirmation screen with media analysis progress, generated child description, whole-draft risk flags, authorization controls, and editable child-world prompt text.
- Confirmation path that reuses the existing draft review and final world creation pattern.
- Default raw-media and preview deletion after final-description confirmation or rejection, with retained accepted description, low-sensitivity provenance, and audit visibility.

### Phase 2 - Quality Enhancements

- Better cross-frame aggregation for video-derived observations.
- Higher-quality audio/transcript aggregation for video-derived final descriptions.
- Stronger action, interaction, and posture signals with evidence references.
- Sampling and reviewer feedback loops for false positives, overconfident claims, and missing unknowns.

### Phase 3 - Productization

- Clear media retention policies and operator-controlled deletion workflows.
- Prompt/model version records and analysis provenance visible in audits.
- Cost and usage controls for repeated analysis attempts and duplicate uploads.
- Safety regression suites for real identifiers, school labels, medical records, violence, trauma, and unsafe inference requests.
