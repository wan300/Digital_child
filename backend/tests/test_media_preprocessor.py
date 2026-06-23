import pytest

from app.core.config import get_settings
from app.services.media_preprocessor import MediaPreprocessor


def test_contact_sheet_builds_three_eight_frame_sheets(tmp_path) -> None:
    try:
        from PIL import Image
    except Exception:
        pytest.skip("Pillow is required for contact sheet generation")

    settings = get_settings()
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    settings.multimodal_contact_sheet_frames_per_sheet = 8
    settings.multimodal_contact_sheet_max_sheets_per_video = 3
    preprocessor = MediaPreprocessor()
    frame_paths = []
    for index in range(24):
        frame_path = tmp_path / f"frame-{index:02d}.jpg"
        Image.new("RGB", (64, 48), (index * 7 % 255, index * 5 % 255, index * 3 % 255)).save(frame_path, "JPEG")
        frame_paths.append(frame_path)

    refs = preprocessor._build_contact_sheets(
        asset_id="asset-1",
        frame_paths=frame_paths,
        duration_seconds=120.0,
        frames_per_sheet=8,
    )

    assert len(refs) == 3
    assert all(ref["kind"] == "contact_sheet" for ref in refs)
    assert [ref["frame_count"] for ref in refs] == [8, 8, 8]
    assert all(len(ref["frames"]) == 8 for ref in refs)
    assert all(ref["grid"] == {"columns": 4, "rows": 2} for ref in refs)
    assert all(ref.get("path") for ref in refs)


def test_video_preprocess_caps_long_video_to_three_contact_sheets(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    settings.multimodal_contact_sheet_frames_per_sheet = 8
    settings.multimodal_contact_sheet_max_sheets_per_video = 3
    video_path = tmp_path / "long.mp4"
    video_path.write_bytes(b"video")
    preprocessor = MediaPreprocessor()
    seen: dict[str, int] = {}

    def fake_extract_contact_sheets(**kwargs):
        seen["frames_per_sheet"] = kwargs["frames_per_sheet"]
        seen["max_frames"] = kwargs["max_frames"]
        return (
            [
                {
                    "ref": f"asset:asset-1#sheet-{index}",
                    "kind": "contact_sheet",
                    "path": str(tmp_path / f"sheet-{index}.jpg"),
                    "frame_count": 8,
                }
                for index in range(1, 4)
            ],
            24,
        )

    monkeypatch.setattr(preprocessor, "_probe_duration", lambda _path: 600.0)
    monkeypatch.setattr(preprocessor, "_extract_contact_sheets", fake_extract_contact_sheets)
    monkeypatch.setattr(preprocessor, "_extract_audio_segments", lambda **_kwargs: [])

    result = preprocessor._preprocess_video("asset-1", str(video_path), "video/mp4")

    assert seen == {"frames_per_sheet": 8, "max_frames": 24}
    assert len(result["preview_refs"]) == 3
    assert result["metadata"]["contact_sheet_frames_per_sheet"] == 8
    assert result["metadata"]["contact_sheet_max_sheets"] == 3
    assert result["metadata"]["sampled_frame_count"] == 24


def test_video_preprocess_without_ffmpeg_does_not_emit_textual_visual_frames(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    settings.multimodal_audio_analysis_enabled = False
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    preprocessor = MediaPreprocessor()
    monkeypatch.setattr("app.services.media_preprocessor.shutil.which", lambda _name: None)

    result = preprocessor._preprocess_video("asset-1", str(video_path), "video/mp4")

    assert result["preview_refs"] == []
    assert result["metadata"]["frame_refs_generated"] == 0
    assert result["metadata"]["frame_files_extracted"] == 0
    assert result["metadata"]["sampled_frame_count"] == 0
    assert result["metadata"]["preprocess_note"] == "no visual frame files extracted"
    assert "video preview frames unavailable" in result["metadata"]["preprocess_warning"]
