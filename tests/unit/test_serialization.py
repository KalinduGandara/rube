"""Unit tests for ``Machine.to_dict`` / ``Machine.from_dict`` (FR-015, design section 4.3)."""

import json

import pytest

from rube.camera import Camera
from rube.entities import Ball, Block, Domino, Floor, Group, Hinge
from rube.errors import RubeValidationError
from rube.machine import Machine


def sample_machine():
    """A machine using every M1 feature: floor, entities, group with hinge, follow camera."""
    m = Machine(name="demo", duration=4.5, floor_size=12)
    ball = m.add(Ball((0, 0, 1), radius=0.12, color="blue", bounciness=0.3))
    m.add(Domino((1, 0, 0), facing_deg=30, tilt_deg=8, name="first"))
    a, b = Block((2, 0, 0), dynamic=False), Block((2, 1, 0), size=(0.3, 0.3, 0.1), mass=2)
    m.add(Group([a, b, Hinge(a, b, pivot=(2, 0.5, 0.2), axis=(1, 0, 0))]))
    m.set_camera(Camera.follow(ball, offset=(-2, -2, 1), lens_mm=50))
    return m


def test_to_dict_format_and_json_safe():
    """FR-015: format 1, settings, flat entities in build order (floor first), constraints."""
    d = sample_machine().to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["format"] == 1
    assert (d["name"], d["duration"], d["floor"], d["floor_size"]) == ("demo", 4.5, True, 12)
    assert [e["name"] for e in d["entities"]] == [
        "Floor_1",
        "Ball_1",
        "first",
        "Block_1",
        "Block_2",
    ]
    assert d["entities"][1] == {
        "type": "Ball", "name": "Ball_1", "center": [0.0, 0.0, 1.0], "radius": 0.12,
        "dynamic": None, "mass": None, "friction": None, "bounciness": 0.3, "color": "blue",
    }  # fmt: skip
    (hinge,) = d["constraints"]
    assert (hinge["type"], hinge["body_a"], hinge["body_b"]) == ("Hinge", "Block_1", "Block_2")
    assert d["camera"] == {
        "mode": "follow",
        "target": "Ball_1",
        "offset": [-2.0, -2.0, 1.0],
        "lens_mm": 50,
    }


def test_roundtrip_equality():
    """FR-015: Machine.from_dict(d).to_dict() == d, and the rebuilt machine builds identically."""
    m = sample_machine()
    d = m.to_dict()
    again = Machine.from_dict(json.loads(json.dumps(d)))
    assert again.to_dict() == d
    assert again.bodies() == m.bodies()
    assert again.constraints() == m.constraints()
    assert again.validate() == []
    assert len([e for e in again.entities if isinstance(e, Floor)]) == 1  # no second auto floor


def test_default_camera_resolved_to_static():
    """FR-015 / D-12: with no camera set, to_dict() stores the auto-framed static camera."""
    m = Machine()
    m.add(Ball((0, 0, 1)))
    cam = m.to_dict()["camera"]
    assert cam["mode"] == "static" and cam["look_at"] == pytest.approx([0, 0, 1])
    assert Machine.from_dict(m.to_dict()).to_dict() == m.to_dict()


def test_to_dict_requires_valid_machine():
    """FR-015: an invalid machine cannot be serialized for Blender."""
    m = Machine()
    m.add(Ball((0, 0, 1), radius=-1))
    with pytest.raises(RubeValidationError):
        m.to_dict()


def test_from_dict_rejects_unknown_format():
    """FR-015: spec.json from another format version is a framework error."""
    d = Machine().to_dict()
    d["format"] = 99
    with pytest.raises(ValueError, match="format"):
        Machine.from_dict(d)
