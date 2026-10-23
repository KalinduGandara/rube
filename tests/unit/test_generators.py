"""Unit tests for ``rube.generators.domino_chain`` (FR-011, FR-013 chain codes)."""

import itertools
import math

import pytest

from rube.entities import Domino, Group
from rube.errors import RubeValidationError
from rube.generators import DominoChain, domino_chain
from rube.machine import Machine
from rube.vec import Vec3

#: The A4 acceptance path: a 90 degree turn through three waypoints on a 4 m quarter circle
#: (start heading +X around center (0, 4), ending heading +Y).
CURVE = [
    (0.0, 0.0, 0.0),
    (4 * math.sin(math.pi / 4), 4 - 4 * math.cos(math.pi / 4), 0.0),
    (4.0, 4.0, 0.0),
]


def codes(item):
    """Set of issue codes reported by ``item.validate()``."""
    return {i.code for i in item.validate()}


def gaps(chain):
    """Straight-line distances between consecutive domino positions."""
    return [(b.position - a.position).length() for a, b in itertools.pairwise(chain.dominoes)]


def yaw_turns(chain):
    """Absolute yaw change between neighbouring dominoes, degrees."""
    return [
        abs((b.facing_deg - a.facing_deg + 180) % 360 - 180)
        for a, b in itertools.pairwise(chain.dominoes)
    ]


def test_straight_chain_default_spacing_and_anchors():
    """FR-011: default spacing = 0.5 x height; anchors first/last/dominoes/start/end."""
    chain = domino_chain([(0, 0, 0), (4, 0, 0)])
    assert isinstance(chain, DominoChain) and isinstance(chain, Group)
    assert chain.validate() == []
    assert len(chain.dominoes) == 11  # 4 m / 0.4 m + 1
    assert all(isinstance(d, Domino) for d in chain.dominoes)
    assert chain.members == chain.dominoes
    assert chain.first is chain.dominoes[0] and chain.last is chain.dominoes[-1]
    assert list(chain.start) == [0, 0, 0] and list(chain.end) == [4, 0, 0]
    assert gaps(chain) == pytest.approx([0.4] * 10)
    assert all(d.facing_deg == pytest.approx(0.0) for d in chain.dominoes)
    assert list(chain.last.position) == pytest.approx([4, 0, 0])


def test_spacing_shorter_than_path_leaves_remainder():
    """FR-011: an explicit spacing places dominoes every `spacing` m from the start."""
    chain = domino_chain([(0, 0, 0), (1.9, 0, 0)], spacing=0.5)
    assert [d.position.x for d in chain.dominoes] == pytest.approx([0, 0.5, 1.0, 1.5])


def test_count_spreads_dominoes_over_whole_path():
    """FR-011: `count` puts the first and last domino on the path ends."""
    chain = domino_chain([(0, 0, 0), (3, 3, 0)], count=8, size=(0.08, 0.3, 0.6))
    assert len(chain.dominoes) == 8
    assert list(chain.last.position) == pytest.approx([3, 3, 0])
    assert all(d.facing_deg == pytest.approx(45.0) for d in chain.dominoes)
    assert all(d.size == (0.08, 0.3, 0.6) for d in chain.dominoes)


def test_tilt_first_and_color():
    """FR-011 / FR-007: only the first domino is tilted (and so starts active); color applies."""
    chain = domino_chain([(0, 0, 0), (2, 0, 0)], tilt_first_deg=10, color="red")
    assert chain.first.tilt_deg == 10
    assert all(d.tilt_deg == 0 for d in chain.dominoes[1:])
    assert all(d.color == "red" for d in chain.dominoes)
    assert chain.first.body().start_deactivated is False
    assert chain.dominoes[1].body().start_deactivated is True


def test_curved_chain_equal_arc_length_spacing_uniform():
    """FR-011 / SPEC 10.2: equal arc-length placement -> straight-line gap spread < 1 mm."""
    chain = domino_chain(CURVE)
    assert chain.validate() == []
    g = gaps(chain)
    assert max(g) - min(g) < 0.001
    # Equal arc length, not equal spline parameter t (which would give uneven gaps).
    assert sum(g) == pytest.approx(0.4 * len(g), abs=0.01)


def test_curved_chain_yaw_follows_tangent():
    """FR-011: facing_deg = atan2(ty, tx) of the path tangent at each domino."""
    chain = domino_chain(CURVE)
    ds = chain.dominoes
    # Quarter circle: heading turns from ~+X to ~+Y (the spline approximates the arc).
    assert ds[0].facing_deg == pytest.approx(0.0, abs=6.0)
    assert ds[-1].facing_deg == pytest.approx(90.0, abs=12.0)
    # The tangent at an inner domino is close to the chord through its neighbours.
    for prev, d, nxt in zip(ds, ds[1:], ds[2:], strict=False):
        chord = nxt.position - prev.position
        expected = math.degrees(math.atan2(chord.y, chord.x))
        assert d.facing_deg == pytest.approx(expected, abs=1.0)
    # Yaw increases monotonically through the left turn.
    assert all(b.facing_deg >= a.facing_deg - 1e-9 for a, b in itertools.pairwise(ds))


def test_chain_in_machine_names_and_order():
    """FR-001 / FR-002: adding the chain registers dominoes in path order with auto names."""
    m = Machine(duration=5)
    chain = m.add(domino_chain([(0, 0, 0), (2, 0, 0)]))
    assert chain.name == "DominoChain_1"
    assert [d.name for d in chain.dominoes] == [f"Domino_{i}" for i in range(1, 7)]
    assert m.entities[1:] == chain.dominoes
    assert m.validate() == []
    d = m.to_dict()
    assert [e["type"] for e in d["entities"]] == ["Floor"] + ["Domino"] * 6
    assert Machine.from_dict(d).to_dict() == d


# --- validation codes ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spacing", "ok"),
    [(0.24, True), (0.6, True), (0.23, False), (0.61, False)],
)
def test_chain_spacing_range(spacing, ok):
    """FR-011: CHAIN_SPACING when spacing is outside [0.3, 0.75] x height, hint gives meters."""
    chain = domino_chain([(0, 0, 0), (5, 0, 0)], spacing=spacing)
    if ok:
        assert "CHAIN_SPACING" not in codes(chain)
        return
    issues = [i for i in chain.validate() if i.code == "CHAIN_SPACING"]
    assert len(issues) == 1
    assert f"{spacing:g}" in issues[0].message
    assert "0.24" in issues[0].hint and "0.6" in issues[0].hint


def test_chain_spacing_from_count_is_checked():
    """FR-011: a count that implies too wide a spacing is CHAIN_SPACING too."""
    issues = [i for i in domino_chain([(0, 0, 0), (5, 0, 0)], count=3).validate()]
    assert [i.code for i in issues] == ["CHAIN_SPACING"]
    assert "count" in issues[0].hint


def test_chain_turn_too_sharp():
    """FR-011: yaw change > 15 deg between neighbours -> CHAIN_TURN with the actual angle."""
    chain = domino_chain([(0, 0, 0), (1, 0, 0), (1, 1, 0)])
    issues = [i for i in chain.validate() if i.code == "CHAIN_TURN"]
    assert len(issues) == 1
    assert "15" in issues[0].message
    assert issues[0].hint
    assert max(yaw_turns(chain)) > 15


def test_chain_not_flat():
    """FR-011: waypoints at different z -> CHAIN_NOT_FLAT."""
    chain = domino_chain([(0, 0, 0), (3, 0, 0.5)])
    issues = [i for i in chain.validate() if i.code == "CHAIN_NOT_FLAT"]
    assert len(issues) == 1 and "0.5" in issues[0].message


@pytest.mark.parametrize(
    ("args", "kwargs", "needle"),
    [
        (([(0, 0, 0)],), {}, "at least 2"),
        (([(0, 0, 0), (0, 0, 0)],), {}, "same"),
        (([(0, 0), (1, 0)],), {}, "(0, 0)"),
        (("abc",), {}, "abc"),
        (([(0, 0, 0), (2, 0, 0)],), {"spacing": 0.4, "count": 5}, "both"),
        (([(0, 0, 0), (2, 0, 0)],), {"count": 1}, "count"),
        (([(0, 0, 0), (2, 0, 0)],), {"count": 2.5}, "count"),
        (([(0, 0, 0), (2, 0, 0)],), {"spacing": -1}, "spacing"),
        (([(0, 0, 0), (0.3, 0, 0)],), {}, "fewer than 2"),
        (([(0, 0, 0), (2, 0, 0)],), {"size": (0.1, 0.4)}, "size"),
        (([(0, 0, 0), (2, 0, 0)],), {"tilt_first_deg": 95}, "95"),
        (([(0, 0, 0), (2, 0, 0)],), {"color": "teal"}, "teal"),
    ],
)
def test_chain_invalid_arguments(args, kwargs, needle):
    """FR-011 / FR-013: unusable arguments -> INVALID_ARGUMENT/OUT_OF_RANGE with the value."""
    chain = domino_chain(*args, **kwargs)
    issues = chain.validate()
    assert issues and all(i.severity == "error" for i in issues)
    assert any(needle in i.message for i in issues), issues
    # No dominoes are generated from unusable arguments, so nothing is reported twice.
    assert chain.dominoes == []


def test_chain_issues_reach_machine_validate():
    """FR-013: Machine.validate() collects chain-level issues (named after the group)."""
    m = Machine()
    m.add(domino_chain([(0, 0, 0), (3, 0, 0)], spacing=0.1))
    issues = [i for i in m.validate() if i.code == "CHAIN_SPACING"]
    assert len(issues) == 1 and issues[0].entity == "DominoChain_1"


def test_chain_anchors_raise_when_empty():
    """D-15: anchors of a chain built from unusable arguments raise RubeValidationError."""
    chain = domino_chain([(0, 0, 0)])
    with pytest.raises(RubeValidationError):
        _ = chain.first
    with pytest.raises(RubeValidationError):
        _ = chain.start


def test_chain_positions_are_on_waypoint_plane():
    """FR-011: dominoes stand on the plane of the (flat) waypoints."""
    chain = domino_chain([(0, 0, 0.5), (2, 0, 0.5)])
    assert all(d.position.z == pytest.approx(0.5) for d in chain.dominoes)
    assert isinstance(chain.start, Vec3)
