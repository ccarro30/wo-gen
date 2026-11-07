import pytest

from wogen import cli, paths

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _has_blender() -> bool:
    try:
        paths.find_blender()
        return True
    except FileNotFoundError:
        return False


needs_blender = pytest.mark.skipif(not _has_blender(), reason="Blender not installed")
needs_base = pytest.mark.skipif(
    not (paths.ASSETS_DIR / "base" / "base_f01.vrm").is_file(), reason="base_f01.vrm not present")


@pytest.mark.blender
@needs_blender
def test_render_test_writes_png(tmp_path):
    out = tmp_path / "render.png"
    assert cli.main(["render-test", "--out", str(out)]) == 0
    assert out.read_bytes()[:8] == PNG_MAGIC


@pytest.mark.blender
@needs_blender
@needs_base
def test_clip_job_bakes_physics_and_writes_mp4(tmp_path):
    out = tmp_path / "clip.mp4"
    args = ["clip", "--preset", "hop", "--width", "128", "--height", "160", "--out", str(out)]
    assert cli.main(args) == 0
    data = out.read_bytes()
    assert len(data) > 1000 and b"ftyp" in data[:64]   # MP4 container header


@pytest.mark.blender
@needs_blender
@needs_base
def test_portrait_job_renders_character(tmp_path):
    out = tmp_path / "portrait.png"
    args = ["portrait", "--framing", "face", "--width", "256", "--height", "256",
            "--expression", "happy", "--out", str(out)]
    assert cli.main(args) == 0
    assert out.read_bytes()[:8] == PNG_MAGIC
