"""Acceptance scenario A12: A2 (ball down a 20 degree ramp) filmed by ``Camera.follow(ball)``.

Run with ``rube run examples/a12_follow_camera.py --out out --video``. Expected: the video
renders, and the ball stays within the middle 50 % of the frame in every still
(``tests/blender/check_camera.py`` verifies this on ``machine.blend``).
"""

import math

from rube import Ball, Camera, Machine, Ramp

machine = Machine(name="a12_follow_camera", duration=4)

# Same layout as examples/a2_ball_down_ramp.py: 2 m of run at 20 degrees, low end on the floor.
run = 2.0
ramp = machine.add(Ramp(start=(-1, 0, run * math.tan(math.radians(20))), end=(1, 0, 0)))
ball = machine.add(Ball(center=ramp.ball_spawn(0.1), radius=0.1))

# The camera keeps (-3, -3, 2) m from the ball and always aims at it.
machine.set_camera(Camera.follow(ball))
