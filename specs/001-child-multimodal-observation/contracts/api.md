# API Contract: 多模态儿童观察草稿

This contract describes the planned user-facing backend interface. It is intentionally
technology-facing for planning, but all endpoints preserve the requirement that media
analysis cannot directly create a child world.

Base path: `/api/worlds/child-observations`

## POST `/media`

Upload one or more media files for a child observation draft.

**Request**:

- Content type: multipart form.
- Fields:
  - `files`: one or more image/video files.
  - `draft_session_id`: optional client-generated grouping id.

**Response `201`**:

```json
{
  "assets": [
    {
      "id": "uuid",
      "media_type": "image",
      "original_filename": "play.jpg",
      "status": "uploaded",
      "sha256": "hex",
      "privacy_flags": [],
      "preview_refs": [],
      "preview_retention": "review_only_delete_with_raw"
    }
  ]
}
```

**Errors**:

- `400`: unsupported media type, unreadable upload, or empty file.
- `413`: server-side request body limit reached; accepted product scope still uses
  bounded processing.
- `422`: malformed multipart request.

## POST `/analysis-jobs`

Start or enqueue a bounded analysis attempt for uploaded assets and structured child
setup fields.

**Request**:

```json
{
  "asset_ids": ["uuid"],
  "structured_setup": {
    "template_key": "curious_outgoing",
    "child_display_name": "小雨",
    "age_months": 48,
    "caregiver_1_label": "照护者一",
    "caregiver_2_label": "照护者二",
    "kindergarten_class": "幼儿园混龄班",
    "peer_count": 2,
    "natural_language_prompt": "",
    "seed": 7
  },
  "include_audio": true,
  "target_child_hint": {
    "description": "穿红色上衣的孩子",
    "operator_selected_asset_ref": "asset:uuid#frame-3"
  }
}
```

**Response `202`**:

```json
{
  "job_id": "uuid",
  "status": "queued",
  "asset_states": {
    "analyzed": [],
    "pending": ["uuid"],
    "skipped": [],
    "excluded": []
  }
}
```

## GET `/analysis-jobs/{job_id}`

Fetch analysis status and normalized result.

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "completed",
  "phase": "completed",
  "asset_states": {
    "analyzed": ["uuid"],
    "pending": [],
    "skipped": [],
    "excluded": []
  },
  "frame_progress": {
    "total": 25,
    "analyzed": 25,
    "failed": 0,
    "pending": 0
  },
  "asset_progress": {
    "uuid": {
      "filename": "play.mp4",
      "media_type": "video",
      "status": "ready",
      "frame_total": 25,
      "frame_analyzed": 25,
      "asr_status": "completed",
      "contribution_batches": [1, 2, 3],
      "error": ""
    }
  },
  "target_child": {
    "description": "系统建议的目标儿童",
    "confidence": 0.82,
    "evidence_refs": ["asset:uuid#frame-3"]
  },
  "observation_draft_id": "uuid",
  "error_message": ""
}
```

## GET `/drafts/{draft_id}`

Fetch an observation draft for final child-description confirmation.

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "in_review",
  "structured_setup": {},
  "target_child": {
    "description": "系统建议的目标儿童",
    "confidence": 0.82,
    "operator_confirmed": false
  },
  "generated_child_description": "小雨在户外活动中主要呈现为愿意观察同伴并参与简单互动的孩子；描述仅基于本次媒体中可见的场景和行为，不包含身份识别、诊断或智力判断。",
  "accepted_child_description": "",
  "observable_summary": "画面中孩子在户外与同伴互动。",
  "visible_observations": [],
  "behavior_signals": [],
  "audio_observations": [],
  "temperament_hypotheses": [],
  "interests": [],
  "development_hints": {},
  "avatar_brief": {},
  "initial_memory_candidates": [],
  "risk_flags": [],
  "unknowns": [],
  "asset_states": {
    "analyzed": [],
    "pending": [],
    "skipped": [],
    "excluded": []
  },
  "preview_refs": []
}
```

## POST `/drafts/{draft_id}/accept-description`

Confirm or edit the final generated child description. This is the default user-facing
path after media analysis.

**Request**:

```json
{
  "description": "小雨在户外活动中愿意靠近同伴并参与简单互动。她会观察周围人的动作，再尝试加入活动；暂不从本次媒体推断诊断、智力、家庭背景或身份信息。",
  "authorization_confirmation": {
    "confirmed": false,
    "authorization_scope": [],
    "risk_categories": [],
    "operator_rationale": ""
  }
}
```

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "description_accepted",
  "accepted_child_description": "小雨在户外活动中愿意靠近同伴并参与简单互动。她会观察周围人的动作，再尝试加入活动；暂不从本次媒体推断诊断、智力、家庭背景或身份信息。",
  "raw_media_deleted": true,
  "risk_flags": []
}
```

**Rules**:

- Prohibited claims such as identity recognition, diagnosis, intelligence judgment, or
  appearance-based personality inference hard-block confirmation.
- High-risk content requires additional authorization only when it is retained in the
  final accepted description.
- Confirmation deletes original media and generated previews; it does not create a
  `SimulationWorld`.

## POST `/drafts/{draft_id}/review`

Legacy compatibility endpoint for per-item review decisions. The default frontend flow
does not call this endpoint.

**Request**:

```json
{
  "target_child_confirmation": {
    "confirmed": true,
    "operator_override": null
  },
  "decisions": [
    {
      "item_path": "interests[0]",
      "decision": "approved",
      "final_value": {
        "content": "对户外跑跳表现出兴趣",
        "confidence": 0.73,
        "evidence_refs": ["asset:uuid#frame-2"]
      },
      "rationale": ""
    }
  ],
  "authorization_confirmation": {
    "confirmed": false,
    "authorization_scope": [],
    "risk_categories": [],
    "operator_rationale": ""
  }
}
```

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "approved",
  "approved_payload": {
    "child_display_name": "小雨",
    "natural_language_prompt": "审核后的观察摘要..."
  },
  "raw_media_deletion_pending": true
}
```

## POST `/drafts/{draft_id}/convert`

Legacy compatibility endpoint that converts an approved or description-accepted
observation draft into the existing child world draft flow. The default frontend flow
now fills the existing child draft template with the accepted description and submits
`source_observation_draft_id` through the normal child draft endpoint.

**Request**:

```json
{
  "start_child_world_draft": true
}
```

**Response `201`**:

```json
{
  "observation_draft_id": "uuid",
  "child_world_draft_id": "uuid",
  "raw_media_deleted": true
}
```

**Rules**:

- Conversion fails if target-specific statements lack target confirmation.
- Conversion fails if unresolved high-risk content lacks additional authorization.
- Conversion never carries prohibited identity/diagnostic/appearance-based claims.
- Conversion creates a normal `ChildWorldDraft`; final world creation still requires
  the existing `/api/worlds/child-drafts/{draft_id}/confirm` review step.

## Existing Child Draft Request Extension

`POST /api/worlds/child-drafts` accepts the existing request body plus optional
`source_observation_draft_id` after a media description has been accepted:

```json
{
  "template_key": "curious_outgoing",
  "child_display_name": "小雨",
  "age_months": 48,
  "caregiver_1_label": "照护者一",
  "caregiver_2_label": "照护者二",
  "kindergarten_class": "幼儿园混龄班",
  "peer_count": 2,
  "natural_language_prompt": "确认后的媒体儿童描述...",
  "seed": 7,
  "source_observation_draft_id": "uuid"
}
```

The endpoint rejects a source observation draft that does not have
`accepted_child_description`, creates only a `ChildWorldDraft`, and stores provenance in
`input_params`. Final world creation still requires `/api/worlds/child-drafts/{draft_id}/confirm`.

## POST `/drafts/{draft_id}/reject`

Reject the observation draft and delete raw media by default.

**Request**:

```json
{
  "reason": "媒体质量不足"
}
```

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "rejected",
  "raw_media_deleted": true
}
```

## DELETE `/media/{asset_id}`

Delete raw media for one asset while retaining permitted metadata and audit records.

**Response `200`**:

```json
{
  "id": "uuid",
  "status": "deleted",
  "deleted_at": "2026-06-18T00:00:00Z"
}
```

## UI Contract

The observer console child draft panel adds these states:

- Media selection and upload progress.
- Analysis queued/running/partial/completed/failed status.
- Media contribution state: analyzed, pending, skipped, excluded.
- Generated final child description in an editable textarea.
- Whole-draft risk display and high-risk authorization capture when retained in the final description.
- A "confirm description and fill template" action that writes the accepted description to the existing `natural_language_prompt`.
- Raw media deletion status after confirmation or rejection.

## MVP Implementation Notes

- If no VLM provider is configured, the backend returns a deterministic generated child
  description rather than failing text-only child draft creation.
- `preview_refs` and raw media are temporary analysis evidence. After final-description
  confirmation or rejection, media files and preview files are deleted and only
  low-sensitivity textual provenance such as `asset:<id>#frame-1`, `asset:<id>#audio-1`,
  or `text:setup` remains.
- Video audio is summarized into the generated child description when available. The MVP does not
  perform voiceprint identification or biometric voice matching.
- Accepted descriptions create normal `ChildWorldDraft` records through the existing
  template flow; world creation still requires the existing
  `/api/worlds/child-drafts/{draft_id}/confirm` endpoint.
