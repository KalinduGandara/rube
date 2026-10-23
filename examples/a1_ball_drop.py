"""Acceptance scenario A1: a ball dropped from 1 m onto the floor.

Expected (``rube run``): status ``ok``; the ball's final z equals its radius (0.1 m) within
0.01 m; it is at rest at the end; the report has no warnings.
"""

from rube import Ball, Machine

machine = Machine(name="a1_ball_drop", duration=3)
machine.add(Ball(center=(0, 0, 1), radius=0.1))
