"""Unit tests for ``Lever`` (FR-012, T-017): plank + fulcrum + hinge structure, anchors,
hinge axis/pivot, validation, serialization round trip and overlap-skip pairs."""

import math

import pytest

from rube import Lever
from rube.entities import DEFAULTS, ENTITY_TYPES, Fulcrum, Hinge, LeverPlank
from rube.errors import RubeValidationError
from rube.machine import Machine
from rube.vec import Vec3, mat_vec


def assert_vec(actual, expected, tol=1e-9):
    """Component-wise Vec3 comparison."""
    assert list(actual) == pytest.approx(list(expected), abs=tol)


def codes(group):
    """Issue codes reported by a group's ``validate()``."""
    return [i.code for i in group.validate()]


def test_members_and_defaults():
    """FR-012: members are Fulcrum, LeverPlank, Hinge; plank dynamic (1 kg, friction 0.5),
    fulcrum passive; both registered entity types."""
    lever = Lever((0, 0, 0.5))
    fulcrum, plank, hinge = lever.members
    assert isinstance(fulcrum, Fulcrum) and isinstance(plank, LeverPlank)
    assert isinstance(hinge, Hinge)
    assert (hinge.body_a, hinge.body_b) == (fulcrum, plank)
    pb, fb = plank.body(), fulcrum.body()
    assert pb.dynamic is True and pb.mass == 1.0 and pb.friction == 0.5
    assert pb.use_deactivation is False and pb.start_deactivated is False
    assert fb.dynamic is False
    assert DEFAULTS["LeverPlank"].margin == 0.001
    assert ENTITY_TYPES["LeverPlank"] is LeverPlank and ENTITY_TYPES["Fulcrum"] is Fulcrum


def test_hinge_pivot_axis_and_collisions():
    """FR-012: hinge at pivot, horizontal axis perpendicular to facing_deg, collisions off."""
    lever = Lever((1, 2, 0.5), facing_deg=30)
    spec = lever.hinge.spec()
    assert_vec(spec.pivot, (1, 2, 0.5))
    a = math.radians(120)  # facing + 90 deg
    assert_vec(spec.axis, (math.cos(a), math.sin(a), 0.0))
    assert spec.disable_collisions is True
    assert (spec.body_a, spec.body_b) == (lever.fulcrum.label, lever.plank.label)


def test_anchors_level():
    """Section 5.2: end anchors are the plank's top-surface end points (level lever)."""
    lever = Lever((0, 0, 0.5), length=2.0, thickness=0.05)
    assert_vec(lever.left_end, (-1.0, 0.0, 0.55))
    assert_vec(lever.right_end, (1.0, 0.0, 0.55))


def test_anchors_follow_facing_and_tilt():
    """tilt_deg lowers the right end (toward facing) by length/2 * sin(tilt) about the pivot."""
    lever = Lever((0, 0, 0.5), length=2.0, thickness=0.05, facing_deg=90, tilt_deg=10)
    t = math.radians(10)
    assert lever.right_end.x == pytest.approx(0.0, abs=1e-9)
    assert lever.right_end.y == pytest.approx(math.cos(t) + 0.05 * math.sin(t))
    assert lever.right_end.z == pytest.approx(0.5 - math.sin(t) + 0.05 * math.cos(t))
    assert lever.left_end.z > lever.right_end.z


def test_plank_pose_rests_on_pivot():
    """The plank's bottom-center is the pivot; its body is a true-size box about its center."""
    lever = Lever((0, 0, 0.5), length=2.0, width=0.3, thickness=0.05, tilt_deg=20)
    body = lever.plank.body()
    bottom = body.location + mat_vec(body.rotation, Vec3(0, 0, -0.025))
    assert_vec(bottom, (0, 0, 0.5), 1e-12)
    xs = [v[0] for v in body.mesh.vertices]
    assert max(xs) - min(xs) == pytest.approx(2.0)


def test_fulcrum_apex_at_pivot_default_height():
    """Fulcrum apex touches the pivot and its base stands at pivot.z - height (default =
    pivot.z, i.e. on the ground); fulcrum_height overrides."""
    for lever, base_z in ((Lever((0, 0, 0.5)), 0.0), (Lever((0, 0, 0.5), fulcrum_height=0.3), 0.2)):
        lo, hi = lever.fulcrum.body().aabb()
        assert lo.z == pytest.approx(base_z) and hi.z == pytest.approx(0.5)
        assert (lo.y + hi.y) / 2 == pytest.approx(0.0)


def test_validation_issues():
    """FR-013: bad arguments are reported once, never raised; anchors raise."""
    assert codes(Lever((0, 0, 0.5))) == []
    assert "INVALID_ARGUMENT" in codes(Lever("x"))
    assert "TOO_SMALL" in codes(Lever((0, 0, 0.5), thickness=0.001))
    assert "OUT_OF_RANGE" in codes(Lever((0, 0, 0.5), length=-1))
    assert "OUT_OF_RANGE" in codes(Lever((0, 0, 0.5), tilt_deg=80))
    assert "OUT_OF_RANGE" in codes(Lever((0, 0, 0.5), fulcrum_height=0))
    bad = Lever("x")
    assert bad.members == []
    with pytest.raises(RubeValidationError):
        _ = bad.left_end


def test_machine_registration_and_roundtrip():
    """D-5/D-17: the group flattens to entities + hinge; from_dict(to_dict) is exact."""
    m = Machine()
    lever = m.add(Lever((0, 0, 0.5), facing_deg=45))
    assert m.validate() == []
    assert [e.label for e in m.entities if not e.type_name() == "Floor"] == [
        "Fulcrum_1", "LeverPlank_1"]  # fmt: skip
    assert lever.name == "Lever_1"
    d = m.to_dict()
    assert Machine.from_dict(d).to_dict() == d
    (spec,) = m.constraints()
    assert spec.body_a == "Fulcrum_1" and spec.body_b == "LeverPlank_1"
