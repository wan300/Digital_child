# Quickstart: 多模态儿童观察草稿验证

This guide describes how to validate the feature after implementation. It is not an
implementation script.

## Prerequisites

- `.env` configured for the backend and model provider.
- Backend dependencies installed with test extras.
- Frontend dependencies installed.
- A vision-capable model configured for media observation analysis; optional audio
  transcription can be enabled for video-derived observations.
- Local writable media directory available under backend data storage.

For SiliconFlow-backed validation, configure the OpenAI-compatible endpoint in local
`.env` without committing secrets:

```powershell
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=replace-with-local-key
MULTIMODAL_MODEL_NAME=moonshotai/Kimi-K2.7-Code
```

The VLM adapter sends local image thumbnails and extracted video key frames as
`image_url` data URLs, while retaining low-sensitivity textual provenance for audit.
Video analysis now uploads media one file at a time, extracts key frames at one frame
per second during the analysis job, sends frames to the VLM in batches of 12, and
transcribes extracted audio segments with SiliconFlow `FunAudioLLM/SenseVoiceSmall`
when a provider key is configured.

## Setup

```powershell
cd backend
uv sync --extra test --extra simulation
uv run alembic upgrade head
```

```powershell
cd frontend
pnpm install
```

## Backend Validation

Run the focused tests:

```powershell
cd backend
uv run pytest tests/test_child_multimodal_observation.py tests/test_child_multimodal_safety.py tests/test_child_multimodal_api.py
```

Run the existing child growth regression tests:

```powershell
cd backend
uv run pytest tests/test_child_growth_mvp.py tests/test_simulation_api.py
```

Expected outcomes:

- Text-only child draft creation still works.
- Media-derived analysis returns `generated_child_description` and never creates a world directly.
- A generated child description can be accepted or edited without per-item observation review.
- High-risk content requires additional authorization or remains blocked.
- Raw media and generated previews are deleted after final-description confirmation or
  rejection.
- Low-confidence multi-child media keeps generated descriptions scene/interaction-level only.
- Large media submissions expose analyzed/pending/skipped/excluded states.

## Frontend Validation

```powershell
cd frontend
pnpm lint
pnpm build
```

Manual observer-console flow:

1. Open the child growth observer console.
2. Fill child alias/custom name, age, caregiver labels, class context, peer count, and
   optional text prompt.
3. Attach one compliant image and start analysis.
4. Confirm that no child world is created at analysis time.
5. Confirm the UI shows upload/extraction/transcription/aggregation progress and a single `AI 生成儿童描述` textarea.
6. Edit the generated child description if needed, then click `确认描述并填入模板`.
7. Confirm raw media and previews are deleted, and the accepted description fills the existing `natural_language_prompt`.
8. Click the existing `生成审核草稿` action and review the generated child world draft using the existing final review panel.
9. Confirm the final draft and verify a paused child growth world is created.

Large video flow:

1. Select 21 videos in the media picker.
2. Confirm the UI uploads files sequentially and keeps already-uploaded files when one
   file fails.
3. Confirm the analysis status moves through queued/running phases for frame extraction,
   audio transcription, frame analysis, and aggregation.
4. Confirm the per-video contribution table shows frame totals, analyzed frames, ASR
   status, failure reason when present, and contributing VLM batch numbers.
5. Confirm the final generated child description is summarized from all completed frame
   batches and audio transcript/status observations.

Multi-child flow:

1. Submit media containing more than one child.
2. Confirm the backend records proposed target confidence.
3. If confidence is low or ambiguous, verify the generated description only keeps
   scene/interaction-level information.
4. Verify no target-specific traits, development conclusions, or memories are produced
   from low-confidence media.

High-risk flow:

1. Submit media or prompt containing explicitly unsafe child-related content or a
   prohibited inference request.
2. Confirm the observation draft is flagged high risk.
3. Remove high-risk content from the final description or continue only with additional
   authorization and scoped rationale when the content is retained.
4. Verify prohibited claims remain blocked even with authorization.

Large media flow:

1. Submit more media than can be analyzed in a single attempt.
2. Confirm the progress view shows analyzed, pending, skipped, and excluded states.
3. Confirm the generated description is based only on media that contributed to the
   current draft.

## Acceptance Evidence To Capture

- Screenshot of the generated child-description confirmation panel.
- Screenshot of whole-draft risk display and high-risk authorization controls.
- Screenshot of raw-media and preview deleted status after description confirmation.
- Backend test output for multimodal safety and existing child draft regression tests.
- Audit records showing upload, analysis, generated description, accepted description,
  child-draft provenance, and deletion lifecycle.

## Implementation Validation Results

Recorded on 2026-06-18:

```powershell
cd backend
uv run pytest tests/test_child_multimodal_api.py tests/test_child_multimodal_observation.py tests/test_child_multimodal_safety.py tests/test_child_growth_mvp.py
```

Result: `12 passed`.

```powershell
cd backend
uv run pytest tests/test_child_multimodal_api.py tests/test_child_multimodal_observation.py tests/test_child_multimodal_safety.py tests/test_child_growth_mvp.py tests/test_simulation_api.py
```

Result: `13 passed`.

```powershell
cd backend
uv run ruff check app tests
```

Result: `All checks passed!`.

```powershell
cd frontend
pnpm.cmd build
```

Result: TypeScript build and Vite production build passed.

```powershell
cd frontend
pnpm.cmd preview --host 127.0.0.1 --port 4173
```

Result: temporary preview server returned `HTTP 200` and was stopped after the smoke
test.

```powershell
cd frontend
node.exe node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173
curl.exe -I --noproxy 127.0.0.1 http://127.0.0.1:5173/
```

Result: Vite HTTP smoke returned `HTTP/1.1 200 OK`.

Browser screenshot note: `npx playwright screenshot` was attempted for desktop/mobile
review, but local Playwright browsers were not installed; `npx playwright install
chromium` timed out in this environment. Build, type-check, and HTTP smoke passed.

Generated-description flow validation recorded on 2026-06-20:

```powershell
cd backend
uv run pytest tests/test_child_multimodal_api.py tests/test_child_multimodal_safety.py
```

Result: `12 passed`.

```powershell
cd frontend
pnpm.cmd build
```

Result: TypeScript build and Vite production build passed.

SiliconFlow feasibility check recorded on 2026-06-18:

- `moonshotai/Kimi-K2.7-Code` returned JSON for text-only chat.
- `moonshotai/Kimi-K2.7-Code` returned JSON for remote image `image_url`.
- `moonshotai/Kimi-K2.7-Code` returned JSON for a local image converted to an
  `image_url` data URL.
- `zai-org/GLM-4.6V` matched the public API documentation example but returned `403`
  with the current local key, so the configured MVP model remains Kimi.

SiliconFlow integration validation recorded on 2026-06-18:

```powershell
cd backend
uv run ruff check app tests
```

Result: `All checks passed!`.

```powershell
cd backend
uv run pytest tests/test_vision_model.py tests/test_child_multimodal_api.py tests/test_child_multimodal_observation.py tests/test_child_multimodal_safety.py tests/test_child_growth_mvp.py tests/test_simulation_api.py
```

Result: `15 passed`.

Real-provider smoke result: local `.env` configured `LLM_BASE_URL=https://api.siliconflow.cn/v1`
and `MULTIMODAL_MODEL_NAME=moonshotai/Kimi-K2.7-Code`; a generated non-child test image
completed upload, thumbnail generation, Kimi VLM analysis, observation draft review,
raw media deletion, conversion to `ChildWorldDraft`, and final paused `SimulationWorld`
creation without deterministic fallback.

```powershell
cd frontend
pnpm.cmd build
```

Result: TypeScript build and Vite production build passed.

Large-video pipeline validation recorded on 2026-06-18:

- Upload stage is stream-based and does not run ffmpeg preprocessing.
- Video preprocessing extracts one frame per second during the analysis job.
- Frame analysis uses VLM batches of 12 frames; a 25-frame fixture splits into
  `12 + 12 + 1`.
- SiliconFlow ASR adapter retries HTTP 429 with the configured retry schedule and then
  either succeeds or marks the audio segment failed.

## Rollback / Recovery Expectations

- If media analysis fails, text-only child draft creation remains available.
- If conversion fails due to high-risk content, raw media remains reviewable until the
  operator rejects, authorizes continuation, or deletion policy runs.
- If final child world confirmation is cancelled, the observation draft remains
  reviewed but no simulation world is created.
