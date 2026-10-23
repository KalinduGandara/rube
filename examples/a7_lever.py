"""Acceptance scenario A7: a ball dropped on one end of a lever lifts the other end.

Expected (``rube run``): the plank tilts about its hinge so the right end rises >= 0.1 m
(report: ``LeverPlank_1.final_tilt_deg`` >= asin(0.1 / (length / 2)) ~ 5.7 deg). Shows the
``Lever`` anchors: ``lever.left_end`` is the top-surface point of the plank's left end; the
ball is dropped 0.15 m in from it (so it lands on the plank, not on its edge) from 0.4 m up.
"""

from rube import Ball, Lever, Machine, Vec3

machine = Machine(name="a7_lever", duration=5)

lever = machine.add(Lever(pivot=(0, 0, 0.5), length=2.0))
drop = lever.left_end + Vec3(0.15, 0, 0.4)  # above the left end; right_end rises
ball = machine.add(Ball(center=drop, radius=0.1))
