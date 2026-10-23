"""Unit tests for ``rube.machine`` (FR-001 container, FR-002 names, FR-003 timing, FR-013)."""

import pytest

from rube.entities import Ball, Block, Domino, Floor, Group, Hinge, HingeSpec
from rube.errors import RubeValidationError, error
from rube.machine import FPS, MAX_BODIES, Machine


def codes(machine):
    """Set of issue codes from ``machine.validate()``."""
    return {i.code for i in machine.validate()}


def issues_with(machine, code):
    """Issues of one code."""
    return [i for i in machine.validate() if i.code == code]


# --- FR-001 container -------------------------------------------------------------------


def test_auto_floor_first_and_optional():
    """FR-001: floor=True adds a passive 20 x 20 x 0.2 Floor first; floor=False adds none."""
    m = Machine()
    assert (m.name, m.duration, m.floor, m.floor_size) == ("machine", 10.0, True, 20.0)
    (floor,) = m.entities
    assert isinstance(floor, Floor) and floor.size == 20.0 and floor.name == "Floor_1"
    assert Machine(floor=False).entities == []
    assert Machine(floor_size=8).entities[0].size == 8
    assert m.validate() == []


def test_add_returns_same_object_and_keeps_order():
    """FR-001: add() returns its argument; build order = registration order."""
    m = Machine()
    a = Ball((0, 0, 1))
    assert m.add(a) is a
    b = m.add(Domino((1, 0, 0)))
    c = m.add(Ball((2, 0, 1)))
    assert m.entities[1:] == [a, b, c]
    assert [s.name for s in m.bodies()] == ["Floor_1", "Ball_1", "Domino_1", "Ball_2"]


def test_add_group_registers_members_in_order():
    """FR-001: adding a Group registers all members (entities and hinges) in order."""
    m = Machine(floor=False)
    p, q = Block((0, 0, 0)), Block((1, 0, 0))
    h = Hinge(p, q, pivot=(0.5, 0, 0.1), axis=(0, 1, 0))
    g = Group([p, h, q])
    assert m.add(g) is g
    assert m.entities == [p, q]
    assert m.hinges == [h]
    assert m.groups == [g]
    assert g.name == "Group_1" and h.name == "Hinge_1"
    assert m.constraints() == [
        HingeSpec("Hinge_1", "Block_1", "Block_2", h.pivot, h.axis.normalized(), True)
    ]


def test_add_rejects_non_entities():
    """FR-001: adding something that is not an Entity/Group is a TypeError naming the type."""
    with pytest.raises(TypeError, match="tuple"):
        Machine().add((0, 0, 1))


# --- FR-002 naming ---------------------------------------------------------------------


def test_auto_names_per_type_and_explicit_names():
    """FR-002: unnamed entities get <Type>_<n> per type; explicit names are kept; taken names
    are skipped."""
    m = Machine(floor=False)
    m.add(Ball((0, 0, 1), name="Ball_2"))
    b1 = m.add(Ball((1, 0, 1)))
    b3 = m.add(Ball((2, 0, 1)))
    d1 = m.add(Domino((3, 0, 0)))
    assert (b1.name, b3.name, d1.name) == ("Ball_1", "Ball_3", "Domino_1")
    assert m.get("Ball_3") is b3
    assert m.validate() == []


def test_name_duplicate():
    """FR-002: two entities with one name -> NAME_DUPLICATE naming it (also adding twice)."""
    m = Machine(floor=False)
    m.add(Ball((0, 0, 1), name="x"))
    m.add(Ball((1, 0, 1), name="x"))
    (issue,) = issues_with(m, "NAME_DUPLICATE")
    assert issue.entity == "x" and "2" in issue.message and issue.hint
    m2 = Machine(floor=False)
    ball = Ball((0, 0, 1))
    m2.add(ball)
    m2.add(ball)
    assert codes(m2) == {"NAME_DUPLICATE"}


# --- FR-003 timing ---------------------------------------------------------------------


@pytest.mark.parametrize(("duration", "end"), [(10.0, 241), (2.5, 61), (1.01, 26), (1, 25)])
def test_frame_range(duration, end):
    """FR-003: 24 fps, frames = ceil(duration * 24), frame_end = 1 + frames."""
    m = Machine(duration=duration)
    assert FPS == 24 and m.frame_start == 1 and m.frame_end == end


def test_frame_range_ignores_float_noise():
    """FR-003: 0.1 * 3 s style float noise must not add a frame (ceil of 24.000000000000004)."""
    m = Machine(duration=(0.1 + 0.2) * 10 / 3)  # 1.0000000000000002 s
    assert m.frame_end == 25


# --- FR-001 / FR-013 machine-level checks ---------------------------------------------


@pytest.mark.parametrize("duration", [0.5, 61, -1])
def test_duration_out_of_range(duration):
    """FR-001: duration outside [1, 60] s -> OUT_OF_RANGE with the value in the message."""
    (issue,) = issues_with(Machine(duration=duration), "OUT_OF_RANGE")
    assert issue.entity is None and f"{duration:g}" in issue.message and issue.hint


def test_bad_machine_arguments_are_issues_not_exceptions():
    """FR-013: garbage arguments never raise from validate()."""
    m = Machine(name="", duration="long", floor="yes", floor_size=-3)
    assert codes(m) >= {"INVALID_ARGUMENT", "OUT_OF_RANGE"}


def test_too_many_bodies():
    """FR-001: more than 500 rigid bodies -> TOO_MANY_BODIES (floor counts)."""
    m = Machine()
    for i in range(MAX_BODIES):
        m.add(Ball((i % 18 - 9, i // 18 * 0.5 - 9, 0.2)))
    (issue,) = issues_with(m, "TOO_MANY_BODIES")
    assert "501" in issue.message
    ok = Machine(floor=False)
    for i in range(MAX_BODIES):
        ok.add(Ball((i, 0, 0.2), mass=1))
    assert "TOO_MANY_BODIES" not in codes(ok)


def test_outside_floor():
    """FR-013: entity center outside the floor area (when a floor exists) -> OUTSIDE_FLOOR."""
    m = Machine(floor_size=4)
    m.add(Ball((2.5, 0, 1)))
    m.add(Ball((1.9, -1.9, 1)))
    (issue,) = issues_with(m, "OUTSIDE_FLOOR")
    assert issue.entity == "Ball_1" and "2.5" in issue.message and "floor_size" in issue.hint
    m2 = Machine(floor=False)
    m2.add(Ball((50, 0, 1)))
    assert "OUTSIDE_FLOOR" not in codes(m2)


def test_mass_ratio_warning_for_near_dynamic_bodies():
    """FR-013: > 100:1 mass ratio between dynamic bodies within 0.05 m -> MASS_RATIO warning."""
    m = Machine()
    m.add(Ball((0, 0, 0.2), radius=0.1, mass=0.05, name="light"))
    m.add(Block((0.13, 0, 0), size=(0.04, 0.4, 0.4), mass=10, name="heavy"))
    (issue,) = issues_with(m, "MASS_RATIO")
    assert issue.severity == "warning"
    assert issue.entity in ("light,heavy", "heavy,light")
    assert "200" in issue.message
    # Far apart, or the heavy one passive -> no warning.
    far = Machine()
    far.add(Ball((0, 0, 0.2), mass=0.05))
    far.add(Block((3, 0, 0), mass=10))
    assert "MASS_RATIO" not in codes(far)
    passive = Machine()
    passive.add(Ball((0, 0, 0.2), mass=0.05))
    passive.add(Block((0.13, 0, 0), size=(0.04, 0.4, 0.4), mass=10, dynamic=False))
    assert "MASS_RATIO" not in codes(passive)


def test_entity_and_group_issues_are_collected():
    """FR-013: validate() returns all entity, hinge and group issues in one pass."""

    class BadGroup(Group):
        def validate(self):
            return [error("CHAIN_SPACING", self.name, "spacing 0.1 m", "use 0.24-0.6 m")]

    m = Machine()
    m.add(Ball((0, 0, 1), radius=-1))
    m.add(Domino((0, 1, 0), friction=2))
    m.add(BadGroup([Ball((1, 1, 1))]))
    assert codes(m) == {"OUT_OF_RANGE", "CHAIN_SPACING"}
    assert len(m.validate()) == 3


def test_hinge_bodies_must_be_registered():
    """FR-013: a hinge referencing an entity not in the machine -> INVALID_ARGUMENT."""
    a, b = Block((0, 0, 0)), Block((1, 0, 0))
    m = Machine(floor=False)
    m.add(Group([a, Hinge(a, b, pivot=(0.5, 0, 0.1), axis=(0, 1, 0))]))
    (issue,) = issues_with(m, "INVALID_ARGUMENT")
    assert issue.entity == "Hinge_1" and "body_b" in issue.message


def test_bodies_requires_valid_machine():
    """FR-020: bodies() on an invalid machine raises RubeValidationError."""
    m = Machine()
    m.add(Ball((0, 0, 1), radius=-1))
    with pytest.raises(RubeValidationError):
        m.bodies()
