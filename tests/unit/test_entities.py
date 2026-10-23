"""Unit tests for ``rube.entities`` (FR-004..FR-007, FR-013 entity checks, FR-020 BodySpec)."""

import json
import math

import pytest

from rube.entities import (
    CLEARANCE,
    COLORS,
    DEFAULTS,
    ENTITY_TYPES,
    Ball,
    Block,
    BodySpec,
    Domino,
    Entity,
    Floor,
    Group,
    Hinge,
    HingeSpec,
    entity_from_dict,
)
from rube.errors import RubeValidationError
from rube.geometry import transform_points
from rube.vec import IDENTITY, Vec3, angle_between_deg, mat_vec, rot_z


def codes(entity):
    """Set of issue codes reported by ``entity.validate()``."""
    return {i.code for i in entity.validate()}


def world_vertices(body: BodySpec):
    """World-space vertices of a BodySpec."""
    return transform_points(body.mesh.vertices, body.rotation, body.location)


def assert_vec(actual, expected, tol=1e-9):
    """Component-wise Vec3 comparison."""
    assert list(actual) == pytest.approx(list(expected), abs=tol)


# --- FR-004 physics defaults -------------------------------------------------------------


def test_defaults_table_matches_spec():
    """FR-004: one DEFAULTS table with the SPEC section 5 values per class."""
    ball = DEFAULTS["Ball"]
    assert (ball.dynamic, ball.mass, ball.friction, ball.bounciness) == (True, 0.5, 0.4, 0.1)
    assert (ball.linear_damping, ball.angular_damping, ball.margin) == (0.04, 0.02, 0.001)
    floor = DEFAULTS["Floor"]
    assert (floor.dynamic, floor.friction, floor.bounciness, floor.margin) == (
        False,
        0.6,
        0.0,
        0.001,
    )
    for t in ("Block", "Domino"):
        row = DEFAULTS[t]
        assert row.dynamic and row.mass is None and row.density == 600
        assert (row.friction, row.bounciness, row.margin) == (0.5, 0.0, 0.001)
        assert (row.linear_damping, row.angular_damping) == (0.04, 0.1)  # Blender defaults
    for row in DEFAULTS.values():
        assert row.color in COLORS


def test_resolved_physics_uses_defaults_and_overrides():
    """FR-004: unset fields come from DEFAULTS; given fields win."""
    p = Ball((0, 0, 1)).resolved_physics()
    assert (p.dynamic, p.mass, p.friction, p.bounciness, p.color) == (True, 0.5, 0.4, 0.1, "red")
    q = Ball((0, 0, 1), mass=2.0, friction=0.9, bounciness=0.5, color="blue", dynamic=False)
    p = q.resolved_physics()
    assert (p.dynamic, p.mass, p.friction, p.bounciness, p.color) == (False, 2.0, 0.9, 0.5, "blue")


def test_density_mass_for_block_and_domino():
    """FR-004: Block/Domino mass defaults to 600 kg/m^3 x box volume."""
    assert Domino((0, 0, 0)).resolved_physics().mass == pytest.approx(600 * 0.1 * 0.4 * 0.8)
    assert Block((0, 0, 0), size=(1, 0.5, 0.2)).resolved_physics().mass == pytest.approx(60.0)
    assert Block((0, 0, 0), mass=3.0).resolved_physics().mass == 3.0


def test_physics_fields_are_keyword_only():
    """FR-004: physics fields are keyword-only (positional use is a TypeError)."""
    with pytest.raises(TypeError):
        Ball((0, 0, 1), 0.1, True)  # type: ignore[misc]


# --- FR-005 Ball -------------------------------------------------------------------------


def test_ball_body_and_anchor():
    """FR-005: UV sphere 32x16, SPHERE shape, center = sphere center, .bottom anchor."""
    ball = Ball((1, 2, 3), radius=0.2, name="B")
    assert isinstance(ball.center, Vec3)
    assert_vec(ball.bottom, (1, 2, 2.8))
    body = ball.body()
    assert body.name == "B" and body.type == "Ball"
    assert body.collision_shape == "SPHERE"
    assert_vec(body.location, (1, 2, 3))
    assert body.rotation == IDENTITY
    assert len(body.mesh.vertices) == 482
    assert body.dynamic and body.mass == 0.5 and body.restitution == 0.1
    assert (body.linear_damping, body.angular_damping, body.margin) == (0.04, 0.02, 0.001)
    assert not body.use_deactivation and not body.start_deactivated
    assert body.color == COLORS["red"]
    lo, hi = body.aabb()
    assert_vec(lo, (0.8, 1.8, 2.8))
    assert_vec(hi, (1.2, 2.2, 3.2))


# --- FR-006 Block ------------------------------------------------------------------------


def test_block_anchors_and_body():
    """FR-006: position = bottom-center; top_center, front on the +facing side; clearance (D-14)."""
    blk = Block((1, 0, 0.5), size=(0.4, 0.2, 0.3), facing_deg=90)
    assert_vec(blk.top_center, (1, 0, 0.8))
    assert_vec(blk.front, (1, 0.2, 0.5))  # half of size x along facing (+Y)
    body = blk.body()
    assert body.collision_shape == "BOX"
    assert_vec(body.location, (1, 0, 0.65 + CLEARANCE))
    assert_vec(mat_vec(body.rotation, Vec3(1, 0, 0)), (0, 1, 0))
    lo, _ = body.aabb()
    assert lo.z == pytest.approx(0.5 + CLEARANCE)
    assert not body.use_deactivation


# --- FR-007 Domino -----------------------------------------------------------------------


def test_upright_domino_anchors_and_deactivation():
    """FR-007 / SPEC 5.1: untilted dominoes start deactivated; anchors on resting pose."""
    d = Domino((0, 0, 0), facing_deg=0)
    assert_vec(d.top_center, (0, 0, 0.8))
    assert_vec(d.front, (0.05, 0, 0))
    body = d.body()
    assert body.use_deactivation and body.start_deactivated
    assert_vec(body.location, (0, 0, 0.4 + CLEARANCE))


@pytest.mark.parametrize("facing", [0, 37, 90, 200])
def test_tilted_domino_keeps_front_edge_on_ground(facing):
    """FR-007: tilt rotates about the bottom front edge, which stays on the ground plane."""
    t, w, h = 0.1, 0.4, 0.8
    d = Domino((1, -2, 0.3), facing_deg=facing, tilt_deg=10, size=(t, w, h), name="D")
    body = d.body()
    verts = world_vertices(body)
    zmin = min(v.z for v in verts)
    assert zmin == pytest.approx(0.3 + CLEARANCE, abs=1e-12)
    lowest = [v for v in verts if abs(v.z - zmin) < 1e-9]
    assert len(lowest) == 2  # exactly the front bottom edge touches
    f = Vec3(math.cos(math.radians(facing)), math.sin(math.radians(facing)), 0)
    for v in lowest:
        rel = v - Vec3(1, -2, 0.3)
        assert rel.dot(f) == pytest.approx(t / 2, abs=1e-9)  # on the front edge line
    # Local +Z is tilted by exactly tilt_deg, toward facing.
    up = mat_vec(body.rotation, Vec3(0, 0, 1))
    assert angle_between_deg(up, Vec3(0, 0, 1)) == pytest.approx(10)
    assert up.dot(f) > 0
    # Front anchor is the pivot edge center; tilted dominoes start active (SPEC 5.1).
    assert_vec(d.front, Vec3(1, -2, 0.3) + f * (t / 2))
    assert body.use_deactivation and not body.start_deactivated


def test_domino_top_center_follows_tilt():
    """FR-007: top_center is the real top-face center of the tilted resting pose."""
    d = Domino((0, 0, 0), tilt_deg=30)
    pivot = Vec3(0.05, 0, 0)
    upright_top = Vec3(0, 0, 0.8)
    expected = pivot + mat_vec(
        ((math.cos(math.radians(30)), 0, math.sin(math.radians(30))),
         (0, 1, 0),
         (-math.sin(math.radians(30)), 0, math.cos(math.radians(30)))),
        upright_top - pivot,
    )  # fmt: skip
    assert_vec(d.top_center, expected)
    assert d.top_center.x > 0.3  # leaned toward +X


# --- Floor -------------------------------------------------------------------------------


def test_floor_body_top_at_zero():
    """FR-001: Floor is a passive box size x size x 0.2 whose top is z = 0."""
    body = Floor(size=20.0, name="Floor_1").body()
    lo, hi = body.aabb()
    assert_vec(lo, (-10, -10, -0.2))
    assert_vec(hi, (10, 10, 0))
    assert not body.dynamic and body.collision_shape == "BOX" and body.friction == 0.6


# --- FR-013 entity-level validation ----------------------------------------------------


def test_valid_entities_have_no_issues():
    """FR-013: defaults validate cleanly."""
    for e in (Ball((0, 0, 1)), Block((0, 0, 0)), Domino((0, 0, 0)), Floor()):
        assert e.validate() == []


@pytest.mark.parametrize(
    ("entity", "code", "needle"),
    [
        (Ball((0, 0, 1), friction=1.5), "OUT_OF_RANGE", "1.5"),
        (Ball((0, 0, 1), bounciness=-0.1), "OUT_OF_RANGE", "-0.1"),
        (Ball((0, 0, 1), mass=0), "OUT_OF_RANGE", "0"),
        (Ball((0, 0, 1), radius=-0.1), "OUT_OF_RANGE", "-0.1"),
        (Domino((0, 0, 0), tilt_deg=-5), "OUT_OF_RANGE", "-5"),
        (Domino((0, 0, 0), tilt_deg=95), "OUT_OF_RANGE", "95"),
        (Ball((0, 0, 1), color="reddish"), "INVALID_ARGUMENT", "reddish"),
        (Ball((0, 0)), "INVALID_ARGUMENT", "(0, 0)"),
        (Block((0, 0, 0), size=(1, 1)), "INVALID_ARGUMENT", "(1, 1)"),
        (Ball((0, 0, 1), dynamic="yes"), "INVALID_ARGUMENT", "yes"),
        (Ball((0, 0, 1), name=""), "INVALID_ARGUMENT", "name"),
        (Ball((0, 0, 1), name="x" * 64), "INVALID_ARGUMENT", "63"),
        (Domino((0, 0, 0), facing_deg="north"), "INVALID_ARGUMENT", "north"),
        (Block((0, 0, 0), size=(0.01, 1, 1)), "TOO_SMALL", "0.01"),
        (Ball((0, 0, 1), radius=0.005), "TOO_SMALL", "0.01"),
        (Floor(size=0.01), "TOO_SMALL", "0.01"),
    ],
)
def test_entity_validation_codes(entity, code, needle):
    """FR-004/FR-013: each bad argument yields its code, a message with the actual number,
    and a non-empty hint."""
    issues = [i for i in entity.validate() if i.code == code]
    assert issues, f"expected {code}, got {entity.validate()}"
    assert any(needle in i.message for i in issues), issues
    assert all(i.severity == "error" and i.hint for i in issues)


def test_invalid_color_lists_valid_names():
    """FR-004: an unknown color's hint lists the valid names."""
    (issue,) = Ball((0, 0, 1), color="reddish").validate()
    for name in ("red", "blue", "green"):
        assert name in issue.hint


def test_validation_collects_all_issues():
    """FR-013: validate() returns every problem at once."""
    b = Ball((0, 0), radius=-1, friction=3, color="nope")
    assert codes(b) == {"INVALID_ARGUMENT", "OUT_OF_RANGE"}
    assert len(b.validate()) == 4


def test_anchor_on_invalid_geometry_raises_but_bad_color_does_not():
    """D-15: anchors need valid geometry; physics/color problems do not block them."""
    with pytest.raises(RubeValidationError) as exc:
        _ = Ball((0, 0), radius=0.1).bottom
    assert exc.value.issues[0].code == "INVALID_ARGUMENT"
    assert_vec(Ball((0, 0, 1), color="nope").bottom, (0, 0, 0.9))


# --- serialization / registry ----------------------------------------------------------


def test_type_registry():
    """FR-015: every concrete entity class registers itself by type name for from_dict."""
    for cls in (Floor, Ball, Block, Domino):
        assert ENTITY_TYPES[cls.__name__] is cls
    assert "Entity" not in ENTITY_TYPES


@pytest.mark.parametrize(
    "entity",
    [
        Ball((0, 0, 1), radius=0.15, name="B", color="blue", mass=1),
        Block((1, 2, 0), size=(0.3, 0.2, 0.1), facing_deg=45, name="K", dynamic=False),
        Domino((0, 0, 0), facing_deg=10, tilt_deg=5, name="D", friction=0.2),
        Floor(size=12.0, name="F"),
    ],
)
def test_entity_dict_roundtrip(entity):
    """FR-015: entity.to_dict() is JSON-safe and from_dict rebuilds an equal record."""
    d = entity.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["type"] == type(entity).__name__
    again = entity_from_dict(d)
    assert type(again) is type(entity)
    assert again.to_dict() == d
    assert again.body() == entity.body()


def test_entity_from_dict_unknown_type():
    """FR-015: unknown type names are a framework error (spec.json is machine-generated)."""
    with pytest.raises(ValueError, match="Rocket"):
        entity_from_dict({"type": "Rocket", "name": "R"})


# --- Group / Hinge (structure for Lever and generators) ---------------------------------


def test_group_holds_members_in_order():
    """FR-001: a Group lists its members (entities and constraints) in order."""
    a, b = Ball((0, 0, 1)), Ball((1, 0, 1))
    h = Hinge(a, b, pivot=(0.5, 0, 1), axis=(0, 1, 0))
    g = Group([a, b, h])
    assert g.members == [a, b, h]
    assert g.entities() == [a, b]
    assert g.hinges() == [h]
    assert g.validate() == []


def test_hinge_spec_and_validation():
    """FR-012 structure: Hinge resolves to a HingeSpec by entity names; bad axis is reported."""
    a, b = Block((0, 0, 0), name="A"), Block((1, 0, 0), name="B")
    h = Hinge(a, b, pivot=(0.5, 0, 0.1), axis=(0, 2, 0), name="H")
    assert h.validate() == []
    spec = h.spec()
    assert spec == HingeSpec("H", "A", "B", Vec3(0.5, 0, 0.1), Vec3(0, 1, 0), True)
    assert h.to_dict() == {
        "type": "Hinge", "name": "H", "body_a": "A", "body_b": "B",
        "pivot": [0.5, 0.0, 0.1], "axis": [0.0, 2.0, 0.0], "disable_collisions": True,
    }  # fmt: skip
    assert Hinge.from_dict(h.to_dict(), {"A": a, "B": b}).to_dict() == h.to_dict()
    bad = Hinge(a, a, pivot=(0, 0), axis=(0, 0, 0))
    assert {i.code for i in bad.validate()} == {"INVALID_ARGUMENT"}
    assert len(bad.validate()) == 3


def test_entity_is_base_of_all():
    """FR-020: every public entity is an Entity with a body()."""
    for cls in (Floor, Ball, Block, Domino):
        assert issubclass(cls, Entity)
    assert isinstance(Domino((0, 0, 0)).body().rotation, tuple)
    assert rot_z(0) == IDENTITY
