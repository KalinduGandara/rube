"""Acceptance scenario A4: a domino chain along a 90 degree curve given by 3 waypoints.

Expected (``rube run``): every domino ``fell_over``.
The waypoints lie on a quarter circle of radius 4 m: the path starts heading +X and ends
heading +Y. Points on an arc (not the corner of an "L") keep the turn between neighbouring
dominoes small, which ``CHAIN_TURN`` requires.
"""

import math

from rube import Machine, domino_chain

machine = Machine(name="a4_curved_chain", duration=8)

r = 4.0
waypoints = [
    (-2, -2, 0),
    (-2 + r * math.sin(math.pi / 4), -2 + r - r * math.cos(math.pi / 4), 0),
    (-2 + r, -2 + r, 0),
]
chain = machine.add(domino_chain(waypoints, tilt_first_deg=10))
