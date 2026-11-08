import pytest

from wogen import bvh

SAMPLE = """HIERARCHY
ROOT Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
  JOINT LeftUpLeg
  {
    OFFSET 1 -1 0
    CHANNELS 3 Zrotation Yrotation Xrotation
    End Site
    {
      OFFSET 0 -5 0
    }
  }
  JOINT Spine
  {
    OFFSET 0 2 0
    CHANNELS 3 Zrotation Yrotation Xrotation
    End Site
    {
      OFFSET 0 3 0
    }
  }
}
MOTION
Frames: 3
Frame Time: 0.0083333
0 16 0 0 0 0  0 0 0  0 0 0
1 16 2 10 20 30  5 0 0  0 0 7
2 15 4 0 0 0  0 0 0  0 0 0
"""


def test_parse_hierarchy_channels_and_frames():
    m = bvh.parse(SAMPLE)
    assert [j.name for j in m.joints] == ["Hips", "LeftUpLeg", "Spine"]
    assert [j.parent for j in m.joints] == [None, 0, 0]
    assert m.joints[1].offset == (1.0, -1.0, 0.0)            # end-site offsets don't overwrite
    assert len(m.frames) == 3 and m.fps == pytest.approx(120, rel=1e-3)
    c = m.channels(0, 1)
    assert c["Xposition"] == 1 and c["Zrotation"] == 10 and list(c)[3:] == ["Zrotation", "Yrotation", "Xrotation"]
    assert m.channels(2, 1)["Xrotation"] == 7


def test_parse_rejects_truncated_motion():
    with pytest.raises(ValueError):
        bvh.parse(SAMPLE.rsplit("\n", 2)[0])


def test_sample_frames_skips_tpose_and_resamples():
    m = bvh.parse(SAMPLE)
    m.frames = m.frames * 100                  # 300 frames at 120 fps
    frames = bvh.sample_frames(m, 24)
    assert frames[0] == 1 and all(b - a == 5 for a, b in zip(frames, frames[1:]))
    assert bvh.sample_frames(m, 24, start=0.5, end=1.0) == list(range(61, 122, 5))


def test_catalog_entries_and_mapping():
    clips = bvh.catalog()
    assert {"walk", "dance", "jog"} <= set(clips)
    for entry in clips.values():
        assert entry["file"].endswith(".bvh") and entry["description"]
    humans = set(bvh.CMU_TO_HUMANOID.values())
    for side in ("left", "right"):
        assert {f"{side}_upper_arm", f"{side}_lower_leg", f"{side}_hand"} <= humans
    with pytest.raises(KeyError):
        bvh.clip_path("no_such_clip")
