from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from pathlib import Path

from app.core.config import get_settings

DEFAULT_UPLOAD_CHUNK_SIZE = 1024 * 1024

SAFE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
}


class UploadTooLargeError(ValueError):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"file exceeds maximum upload size of {_format_bytes(max_bytes)}")


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "upload"


def media_type_from_content(content_type: str, filename: str) -> str | None:
    lowered = (content_type or "").lower()
    suffix = Path(filename or "").suffix.lower()
    if lowered.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if lowered.startswith("video/") or suffix in {".mp4", ".mov", ".m4v", ".webm", ".avi"}:
        return "video"
    return None


class MediaStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.media_dir = Path(settings.multimodal_media_dir)
        self.preview_dir = Path(settings.multimodal_preview_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)

    def build_storage_path(self, asset_id: str, filename: str) -> Path:
        suffix = Path(filename).suffix.lower()
        if suffix not in SAFE_SUFFIXES:
            suffix = ".bin"
        return self.media_dir / f"{asset_id}{suffix}"

    def preview_path(self, asset_id: str, label: str, suffix: str = ".jpg") -> Path:
        safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_") or "preview"
        return self.preview_dir / f"{asset_id}_{safe_label}{suffix}"

    async def save_bytes(self, *, asset_id: str, filename: str, data: bytes, max_bytes: int | None = None) -> tuple[Path, str, int]:
        if not data:
            raise ValueError("empty upload")
        if max_bytes is not None and max_bytes > 0 and len(data) > max_bytes:
            raise UploadTooLargeError(max_bytes)
        storage_path = self.build_storage_path(asset_id, filename)
        storage_path.write_bytes(data)
        return storage_path, hashlib.sha256(data).hexdigest(), len(data)

    async def save_upload_stream(
        self,
        *,
        asset_id: str,
        filename: str,
        upload: object,
        chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
        max_bytes: int | None = None,
    ) -> tuple[Path, str, int]:
        storage_path = self.build_storage_path(asset_id, filename)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with storage_path.open("wb") as handle:
                while True:
                    chunk = await upload.read(chunk_size)  # type: ignore[attr-defined]
                    if not chunk:
                        break
                    if max_bytes is not None and max_bytes > 0 and size_bytes + len(chunk) > max_bytes:
                        raise UploadTooLargeError(max_bytes)
                    size_bytes += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
        except UploadTooLargeError:
            with suppress(OSError):
                storage_path.unlink()
            raise
        if size_bytes == 0:
            with suppress(OSError):
                storage_path.unlink()
            raise ValueError("empty upload")
        return storage_path, digest.hexdigest(), size_bytes

    def delete_paths(self, storage_path: str | None, preview_refs: list[dict] | None = None) -> list[str]:
        deleted: list[str] = []
        candidates: list[Path] = []
        if storage_path:
            candidates.append(Path(storage_path))
        for ref in preview_refs or []:
            path = ref.get("path") if isinstance(ref, dict) else None
            if path:
                candidates.append(Path(path))
        for path in candidates:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted.append(str(path))
            except OSError:
                continue
        return deleted


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / 1024 / 1024:.1f} MB"
