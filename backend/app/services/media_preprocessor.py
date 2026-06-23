from __future__ import annotations

import math
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.media_storage import MediaStorage


class MediaPreprocessor:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = MediaStorage()

    def preprocess(self, *, asset_id: str, media_type: str, storage_path: str, mime_type: str) -> dict[str, Any]:
        if media_type == "image":
            return self._preprocess_image(asset_id, storage_path, mime_type)
        if media_type == "video":
            return self._preprocess_video(asset_id, storage_path, mime_type)
        return {"status": "failed", "preview_refs": [], "metadata": {"error": "unsupported media type"}}

    def _preprocess_image(self, asset_id: str, storage_path: str, mime_type: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {"mime_type": mime_type}
        preview_refs: list[dict[str, Any]] = []
        try:
            from PIL import Image, ImageOps

            with Image.open(storage_path) as image:
                image = ImageOps.exif_transpose(image)
                metadata["width"], metadata["height"] = image.size
                preview = image.copy()
                preview.thumbnail((480, 480))
                preview_path = self.storage.preview_path(asset_id, "thumb")
                if preview.mode not in {"RGB", "L"}:
                    preview = preview.convert("RGB")
                preview.save(preview_path, "JPEG", quality=82)
                preview_refs.append(
                    {
                        "ref": f"asset:{asset_id}#thumb",
                        "kind": "thumbnail",
                        "path": str(preview_path),
                        "review_only": True,
                        "deleted_with_raw": True,
                    }
                )
        except Exception as exc:
            metadata["preprocess_warning"] = f"image preview unavailable: {type(exc).__name__}"
            preview_refs.append(
                {
                    "ref": f"asset:{asset_id}#image",
                    "kind": "image_reference",
                    "review_only": True,
                    "deleted_with_raw": True,
                }
            )
        return {"status": "ready", "preview_refs": preview_refs, "metadata": metadata}

    def _preprocess_video(self, asset_id: str, storage_path: str, mime_type: str) -> dict[str, Any]:
        path = Path(storage_path)
        frame_interval = max(1, int(self.settings.multimodal_frame_interval_seconds))
        frames_per_sheet = max(1, int(self.settings.multimodal_contact_sheet_frames_per_sheet))
        max_sheets = max(1, int(self.settings.multimodal_contact_sheet_max_sheets_per_video))
        max_frames = frames_per_sheet * max_sheets
        duration_seconds = self._probe_duration(path)
        preview_refs, sampled_frame_count = self._extract_contact_sheets(
            asset_id=asset_id,
            storage_path=path,
            duration_seconds=duration_seconds,
            frame_interval=frame_interval,
            frames_per_sheet=frames_per_sheet,
            max_frames=max_frames,
        )
        frame_note = "ffmpeg contact sheets extracted" if preview_refs else "no visual frame files extracted"
        preprocess_warning = "" if preview_refs else "video preview frames unavailable; install ffmpeg/ffprobe or submit a decodable video"
        audio_refs = self._extract_audio_segments(asset_id=asset_id, storage_path=path, duration_seconds=duration_seconds)
        return {
            "status": "ready",
            "preview_refs": preview_refs,
            "metadata": {
                "mime_type": mime_type,
                "size_bytes": path.stat().st_size if path.exists() else None,
                "duration_seconds": duration_seconds,
                "frame_interval_seconds": frame_interval,
                "frame_refs_generated": len(preview_refs),
                "frame_files_extracted": sum(1 for ref in preview_refs if ref.get("path")),
                "contact_sheet_frames_per_sheet": frames_per_sheet,
                "contact_sheet_max_sheets": max_sheets,
                "sampled_frame_count": sampled_frame_count,
                "audio_track_retained": bool(audio_refs),
                "audio_refs": audio_refs,
                "preprocess_note": frame_note,
                "preprocess_warning": preprocess_warning,
            },
        }

    def _probe_duration(self, storage_path: Path) -> float | None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe or not storage_path.exists():
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(storage_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return max(0.0, float(result.stdout.strip()))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _extract_contact_sheets(
        self,
        *,
        asset_id: str,
        storage_path: Path,
        duration_seconds: float | None,
        frame_interval: int,
        frames_per_sheet: int,
        max_frames: int,
    ) -> tuple[list[dict[str, Any]], int]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not storage_path.exists():
            return [], 0
        output_pattern = self.storage.preview_dir / f"{asset_id}_sample-%03d.jpg"
        fps_value = _balanced_fps(duration_seconds=duration_seconds, max_frames=max_frames, frame_interval=frame_interval)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(storage_path),
            "-vf",
            f"fps={fps_value},scale=240:-2",
            "-frames:v",
            str(max_frames),
            str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            return [], 0
        frame_paths = sorted(self.storage.preview_dir.glob(f"{asset_id}_sample-*.jpg"))[:max_frames]
        if not frame_paths:
            return [], 0
        try:
            refs = self._build_contact_sheets(
                asset_id=asset_id,
                frame_paths=frame_paths,
                duration_seconds=duration_seconds,
                frames_per_sheet=frames_per_sheet,
            )
        finally:
            for frame_path in frame_paths:
                with suppress(OSError):
                    frame_path.unlink(missing_ok=True)
        return refs, len(frame_paths)

    def _build_contact_sheets(
        self,
        *,
        asset_id: str,
        frame_paths: list[Path],
        duration_seconds: float | None,
        frames_per_sheet: int,
    ) -> list[dict[str, Any]]:
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return []
        refs: list[dict[str, Any]] = []
        cell_width = 240
        cell_height = 170
        columns = min(4, max(1, frames_per_sheet))
        rows = math.ceil(frames_per_sheet / columns)
        for sheet_index, start in enumerate(range(0, len(frame_paths), frames_per_sheet), start=1):
            group = frame_paths[start : start + frames_per_sheet]
            sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
            draw = ImageDraw.Draw(sheet)
            frame_refs: list[dict[str, Any]] = []
            for offset, frame_path in enumerate(group):
                try:
                    with Image.open(frame_path) as image:
                        image = image.convert("RGB")
                        image.thumbnail((cell_width, cell_height - 18))
                        x = (offset % columns) * cell_width + (cell_width - image.width) // 2
                        y = (offset // columns) * cell_height + 18 + (cell_height - 18 - image.height) // 2
                        sheet.paste(image, (x, y))
                except OSError:
                    continue
                frame_number = start + offset + 1
                timestamp_seconds = _estimated_timestamp(frame_number, total_frames=len(frame_paths), duration_seconds=duration_seconds)
                draw.text(((offset % columns) * cell_width + 6, (offset // columns) * cell_height + 4), f"{frame_number}: {timestamp_seconds:.1f}s", fill=(40, 40, 40))
                frame_refs.append(
                    {
                        "ref": f"asset:{asset_id}#t={timestamp_seconds:.1f}s",
                        "kind": "sampled_frame",
                        "segment_label": f"t={timestamp_seconds:.1f}s",
                        "timestamp_seconds": timestamp_seconds,
                    }
                )
            if not frame_refs:
                continue
            sheet_timestamp = float(frame_refs[0].get("timestamp_seconds") or 0)
            sheet_path = self.storage.preview_dir / f"{asset_id}_sheet-{sheet_index:03d}.jpg"
            sheet.save(sheet_path, "JPEG", quality=84)
            refs.append(
                {
                    "ref": f"asset:{asset_id}#sheet-{sheet_index}",
                    "kind": "contact_sheet",
                    "segment_label": f"sheet-{sheet_index}",
                    "path": str(sheet_path),
                    "timestamp_seconds": sheet_timestamp,
                    "frame_count": len(frame_refs),
                    "frames": frame_refs,
                    "grid": {"columns": columns, "rows": rows},
                    "review_only": True,
                    "deleted_with_raw": True,
                }
            )
        return refs

    def _extract_audio_segments(self, *, asset_id: str, storage_path: Path, duration_seconds: float | None) -> list[dict[str, Any]]:
        if not self.settings.multimodal_audio_analysis_enabled:
            return []
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not storage_path.exists():
            return [
                {
                    "ref": f"asset:{asset_id}#audio-1",
                    "kind": "audio_segment",
                    "segment_label": "audio-1",
                    "review_only": True,
                    "deleted_with_raw": True,
                    "status": "metadata_only",
                }
            ]
        segment_seconds = 3500 if duration_seconds is None or duration_seconds > 3500 else None
        if segment_seconds:
            output_pattern = self.storage.preview_dir / f"{asset_id}_audio-%03d.mp3"
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(storage_path),
                "-vn",
                "-ac",
                "1",
                "-b:a",
                "64k",
                "-f",
                "segment",
                "-segment_time",
                str(segment_seconds),
                "-reset_timestamps",
                "1",
                str(output_pattern),
            ]
        else:
            output_path = self.storage.preview_dir / f"{asset_id}_audio-001.mp3"
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(storage_path),
                "-vn",
                "-ac",
                "1",
                "-b:a",
                "64k",
                str(output_path),
            ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            return [
                {
                    "ref": f"asset:{asset_id}#audio-1",
                    "kind": "audio_segment",
                    "segment_label": "audio-1",
                    "review_only": True,
                    "deleted_with_raw": True,
                    "status": "extract_failed",
                }
            ]
        refs: list[dict[str, Any]] = []
        for index, audio_path in enumerate(sorted(self.storage.preview_dir.glob(f"{asset_id}_audio-*.mp3")), start=1):
            if not audio_path.exists() or audio_path.stat().st_size == 0:
                continue
            refs.append(
                {
                    "ref": f"asset:{asset_id}#audio-{index}",
                    "kind": "audio_segment",
                    "segment_label": f"audio-{index}",
                    "path": str(audio_path),
                    "size_bytes": audio_path.stat().st_size,
                    "review_only": True,
                    "deleted_with_raw": True,
                    "status": "ready",
                }
            )
        return refs


def _balanced_fps(*, duration_seconds: float | None, max_frames: int, frame_interval: int) -> str:
    if duration_seconds and duration_seconds > 0:
        return f"{max_frames}/{duration_seconds:.3f}"
    return f"1/{frame_interval}" if frame_interval > 1 else "1"


def _estimated_timestamp(frame_number: int, *, total_frames: int, duration_seconds: float | None) -> float:
    if duration_seconds and duration_seconds > 0 and total_frames > 1:
        return round((frame_number - 1) * duration_seconds / (total_frames - 1), 1)
    return float(frame_number - 1)
