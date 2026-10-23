"""Acceptance scenario A2: a ball rolls down a 20 degree ramp and out onto the floor.

Expected (``rube run``): the ball's final x is beyond ``ramp.bottom.x``; no ``UNSTABLE``.
Shows the ramp anchors: ``ball_spawn(radius)`` puts the ball just above the top of the ramp.
"""

import math

from rube import Ball, Machine, Ramp

machine = Machine(name="a2_ball_down_ramp", duration=4)

# 2 m of horizontal run at 20 degrees; the low end meets the floor (z = 0).
run = 2.0
ramp = machine.add(Ramp(start=(-1, 0, run * math.tan(math.radians(20))), end=(1, 0, 0)))
machine.add(Ball(center=ramp.ball_spawn(0.1), radius=0.1))
