"""Acceptance scenario A6: a ball rolls down a 2-turn spiral ramp and out onto the floor.

Expected (``rube run``): the ball passes within 0.3 m of ``spiral.exit`` and never leaves
the floor area. Shows the spiral anchors: ``spiral.ball_spawn(r)`` puts the ball in the
groove just after the entry (and enables the TRACK_TOO_NARROW check for that radius).

Slope = height / (2 pi radius turns) = 1.5 / (2 pi 0.8 2) ~ 8.5 deg (allowed 4-25 deg).
The 0.08 m ball fits the default track: track_width 0.25 >= 2.5 r, wall_height 0.08 >= 0.6 r.
"""

from rube import Ball, Machine, spiral_ramp

machine = Machine(name="a6_spiral", duration=8)

spiral = machine.add(spiral_ramp(center=(0, 0, 0), radius=0.8, height=1.5, turns=2))
ball = machine.add(Ball(center=spiral.ball_spawn(0.08), radius=0.08))
