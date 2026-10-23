"""Unit tests for ``rube.analysis`` (FR-023, T-009): sampled tracks -> report records."""

import math

import pytest

from rube.analysis import Track, analyze, rotation_angle_deg, tilt_deg
from rube.vec import IDENTITY, Vec3, rot_axis, rot_z

FPS = 24


def still(name="Ball_1", kind="Ball", n=48, pos=(0.0, 0.0, 0.1), rot=IDENTITY):
    """A track that never moves: ``n`` identical samples."""
    return Track(name, kind, [Vec3(*pos)] * n, [rot] * n)


def moving(positions, rotations=None, name="Ball_1", kind="Ball"):
    """A track from explicit positions (tuples) and optional rotations (default identity)."""
    pts = [Vec3(*p) for p in positions]
    return Track(name, kind, pts, rotations or [IDENTITY] * len(pts))


def record(result, name="Ball_1"):
    """The entity record called ``name``."""
    return next(e for e in result.entities if e["name"] == name)


def test_record_has_report_keys_and_values():
    """FR-023 / FR-025: record carries every SPEC 9.2 entity key with initial/final values."""
    track = moving([(0, 0, 1)] * 10 + [(0, 0, 0.5)] * 10)
    rec = record(analyze([track], fps=FPS, frame_start=1))
    assert list(rec) == [
        "name", "type", "initial_position", "final_position", "first_motion_frame",
        "first_motion_time_s", "max_speed", "final_tilt_deg", "fell_over", "left_bounds",
        "at_rest_at_end",
    ]  # fmt: skip
    assert rec["type"] == "Ball"
    assert rec["initial_position"] == [0, 0, 1]
    assert rec["final_position"] == [0, 0, 0.5]


def test_first_motion_displacement_threshold():
    """FR-023: first motion = first frame whose displacement from frame 1 exceeds 5 mm."""
    zs = [1.0, 1.0, 0.998, 0.996, 0.994, 0.99]  # 2, 4, 6 mm: frame index 4 is the first > 5 mm
    track = moving([(0, 0, z) for z in zs])
    rec = record(analyze([track], fps=FPS, frame_start=1))
    assert rec["first_motion_frame"] == 5  # frame_start 1 + index 4
    assert rec["first_motion_time_s"] == pytest.approx(4 / FPS, abs=1e-4)


def test_first_motion_exactly_5mm_is_not_motion():
    """FR-023: displacement must be strictly greater than 5 mm."""
    track = moving([(0, 0, 0.0), (0, 0, 0.005), (0, 0, 0.005)])  # exact binary 5 mm
    rec = record(analyze([track], fps=FPS, frame_start=1))
    assert rec["first_motion_frame"] is None
    assert rec["first_motion_time_s"] is None


def test_first_motion_rotation_threshold():
    """FR-023: a pure rotation > 2 degrees vs frame 1 also counts as motion."""
    rots = [IDENTITY, rot_z(1.0), rot_z(1.9), rot_z(2.5), rot_z(4.0)]
    track = moving([(0, 0, 0.1)] * 5, rots)
    rec = record(analyze([track], fps=FPS, frame_start=10))
    assert rec["first_motion_frame"] == 13
    assert rec["first_motion_time_s"] == pytest.approx(3 / FPS, abs=1e-4)


def test_rotation_angle_and_tilt_helpers():
    """FR-023: rotation change = angle of R0^T R; tilt = angle of local +Z vs world +Z."""
    assert rotation_angle_deg(IDENTITY, rot_z(30)) == pytest.approx(30)
    assert rotation_angle_deg(rot_z(10), rot_z(10)) == pytest.approx(0, abs=1e-6)
    assert tilt_deg(rot_z(80)) == pytest.approx(0, abs=1e-6)
    assert tilt_deg(rot_axis(Vec3(0, 1, 0), 75)) == pytest.approx(75)


def test_max_speed_from_frame_differences():
    """FR-023: speed = |delta position| * fps between consecutive frames (m/s)."""
    track = moving([(0, 0, 1), (0.1, 0, 1), (0.1, 0, 1), (0.1, 0.3, 1.4)])
    rec = record(analyze([track], fps=FPS, frame_start=1))
    assert rec["max_speed"] == pytest.approx(0.5 * FPS, rel=1e-3)


def test_fell_over_only_for_dominoes_and_blocks():
    """FR-023: fell_over = Domino/Block with final tilt > 60 degrees; event at first such frame."""
    tilts = [0, 10, 30, 61, 85, 85]
    rots = [rot_axis(Vec3(0, 1, 0), t) for t in tilts]
    domino = moving([(0, 0, 0.4)] * 6, rots, name="Domino_1", kind="Domino")
    ball = moving([(1, 0, 0.1)] * 6, rots, name="Ball_1", kind="Ball")
    result = analyze([domino, ball], fps=FPS, frame_start=1)
    assert record(result, "Domino_1")["fell_over"] is True
    assert record(result, "Domino_1")["final_tilt_deg"] == pytest.approx(85, abs=0.01)
    assert record(result, "Ball_1")["fell_over"] is False
    fell = [e for e in result.events if e["event"] == "fell_over"]
    assert fell == [{"frame": 4, "time_s": pytest.approx(3 / FPS, abs=1e-4), "entity": "Domino_1",
                     "event": "fell_over"}]  # fmt: skip


def test_tilt_below_60_is_not_fallen():
    """FR-023: a Block tilted just under 60 degrees has not fallen over."""
    rot = rot_axis(Vec3(1, 0, 0), 59.9)
    block = moving([(0, 0, 0.1)] * 3, [IDENTITY, rot, rot], name="Block_1", kind="Block")
    result = analyze([block], fps=FPS, frame_start=1)
    assert record(result, "Block_1")["fell_over"] is False
    assert not [e for e in result.events if e["event"] == "fell_over"]


def test_left_bounds_outside_floor_area():
    """FR-023: left_bounds when the center leaves the floor area (|x| or |y| > half size)."""
    track = moving([(9.5, 0, 0.1), (9.9, 0, 0.1), (10.2, 0, 0.0), (10.5, 0, -0.5)])
    result = analyze([track], fps=FPS, frame_start=1, floor_half_size=10.0)
    assert record(result)["left_bounds"] is True
    assert [e for e in result.events if e["event"] == "left_bounds"] == [
        {
            "frame": 3,
            "time_s": pytest.approx(2 / FPS, abs=1e-4),
            "entity": "Ball_1",
            "event": "left_bounds",
        }
    ]


def test_left_bounds_below_minus_one_without_floor():
    """FR-023: without a floor, only z < -1 counts as leaving bounds."""
    track = moving([(50, 0, 0), (50, 0, -0.9), (50, 0, -1.2)])
    result = analyze([track], fps=FPS, frame_start=1, floor_half_size=None)
    assert record(result)["left_bounds"] is True
    assert result.events[-1]["frame"] == 3
    inside = analyze([moving([(50, 0, 0)] * 3)], fps=FPS, frame_start=1)
    assert record(inside)["left_bounds"] is False


def test_at_rest_uses_last_half_second():
    """FR-023: at_rest_at_end = speed < 0.01 m/s for every step in the last 0.5 s."""
    n = 48
    moving_early = [(0.01 * i, 0, 0.1) for i in range(24)] + [(0.24, 0, 0.1)] * (n - 24)
    assert record(analyze([moving([*moving_early])], fps=FPS))["at_rest_at_end"] is True
    # A slow drift of 0.012 m/s inside the window is not rest.
    drift = [(0.0005 * i, 0, 0.1) for i in range(n)]
    assert record(analyze([moving(drift)], fps=FPS))["at_rest_at_end"] is False
    # Motion just before the 0.5 s window does not matter.
    late = [(0.0, 0, 0.1)] * (n - 13) + [(0.1, 0, 0.1)] * 13
    assert record(analyze([moving(late)], fps=FPS))["at_rest_at_end"] is True
    late_in_window = [(0.0, 0, 0.1)] * (n - 12) + [(0.1, 0, 0.1)] * 12
    assert record(analyze([moving(late_in_window)], fps=FPS))["at_rest_at_end"] is False


def test_still_body_has_no_events_or_issues():
    """FR-023: a body that never moves: no first motion, at rest, no events, no UNSTABLE."""
    result = analyze([still()], fps=FPS, frame_start=1, floor_half_size=10.0)
    rec = record(result)
    assert rec["first_motion_frame"] is None
    assert rec["max_speed"] == 0
    assert rec["at_rest_at_end"] is True
    assert result.events == []
    assert result.issues == []


def test_events_sorted_by_frame_across_entities():
    """FR-023: events from all entities are sorted by frame (ties: entity order, then kind)."""
    a = moving([(0, 0, 1)] * 5 + [(0, 0, 0.5)] * 5, name="A")
    b = moving([(0, 0, 1)] * 2 + [(0, 0, 0.5)] * 8, name="B")
    c = moving([(0, 0, 1)] * 2 + [(0, 0, 0.5)] * 8, name="C")
    result = analyze([a, b, c], fps=FPS, frame_start=1)
    assert [(e["frame"], e["entity"]) for e in result.events] == [(3, "B"), (3, "C"), (6, "A")]
    assert all(e["event"] == "started_moving" for e in result.events)


def test_unstable_on_speed_above_30():
    """FR-023: UNSTABLE warning when max_speed > 30 m/s, naming the entity and the speed."""
    step = 31.0 / FPS
    track = moving([(0, 0, 1), (step, 0, 1), (2 * step, 0, 1)], name="Ball_7")
    result = analyze([track], fps=FPS, frame_start=1)
    [issue] = result.issues
    assert (issue.severity, issue.code, issue.entity) == ("warning", "UNSTABLE", "Ball_7")
    assert "31.0 m/s" in issue.message
    assert issue.hint


def test_unstable_on_jump_above_2m_in_one_frame():
    """FR-023: UNSTABLE warning when a body moves > 2 m in one frame (even at a low fps)."""
    track = moving([(0, 0, 1), (0, 0, 1), (2.5, 0, 1)], name="Domino_2", kind="Domino")
    result = analyze([track], fps=10, frame_start=1)  # 25 m/s: below the speed limit
    [issue] = result.issues
    assert issue.code == "UNSTABLE" and issue.entity == "Domino_2"
    assert "2.50 m in one frame" in issue.message


def test_speed_exactly_30_is_stable():
    """FR-023: the speed limit is strictly greater than 30 m/s."""
    step = 30.0 / FPS
    track = moving([(0, 0, 1), (step, 0, 1)])
    assert analyze([track], fps=FPS).issues == []


def test_empty_tracks():
    """FR-023: a machine with no dynamic bodies yields empty records."""
    result = analyze([], fps=FPS, frame_start=1)
    assert (result.entities, result.events, result.issues) == ([], [], [])


def test_track_length_mismatch_rejected():
    """Track positions and rotations must cover the same frames (framework bug otherwise)."""
    with pytest.raises(ValueError):
        Track("X", "Ball", [Vec3(0, 0, 0)] * 2, [IDENTITY])


def test_values_are_json_numbers():
    """FR-025: record values are plain floats/ints/bools, finite (JSON-safe)."""
    track = moving([(0, 0, 1), (0, 0, 0.9), (0, 0, 0.8)])
    rec = record(analyze([track], fps=FPS))
    for v in rec["final_position"] + [rec["max_speed"], rec["final_tilt_deg"]]:
        assert isinstance(v, float | int) and math.isfinite(v)
