"""Acceptance scenario A5: a ball rolls down a ramp and knocks over a domino chain (no tilt).

Expected (``rube run``): the first domino's ``started_moving`` comes after the ball's, and the
last domino ``fell_over``. Running it twice gives identical final positions (A9).

Why 0.4 m dominoes: the default 0.5 kg ball cannot topple a default 0.8 m domino (19.2 kg at
600 kg/m^3); a 0.4 m domino (2.4 kg) falls easily. Spacing defaults to half the height.
"""

import math

from rube import Ball, Machine, Ramp, domino_chain

machine = Machine(name="a5_ball_ramp_chain", duration=8)

# 20 degree ramp with 2 m of run; its low end meets the floor at x = -1.
ramp = machine.add(Ramp(start=(-3, 0, 2 * math.tan(math.radians(20))), end=(-1, 0, 0)))
ball = machine.add(Ball(center=ramp.ball_spawn(0.1), radius=0.1))

# The chain starts on the floor 0.5 m past the ramp and runs straight on to x = 3.
chain = machine.add(domino_chain([ramp.exit(0.5), (3, 0, 0)], size=(0.05, 0.2, 0.4)))
