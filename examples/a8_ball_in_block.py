"""Acceptance scenario A8: a ball placed so that it intersects a block.

Expected (``rube run``): status ``invalid`` with an ``OVERLAP`` error naming both
``Block_1`` and ``Ball_1``; the overlap is found before the bake, so nothing is simulated.
Static validation (``rube check``) passes: overlaps are detected inside Blender (FR-021).
"""

from rube import Ball, Block, Machine

machine = Machine(name="a8_ball_in_block", duration=2)
block = machine.add(Block(position=(0, 0, 0), size=(0.4, 0.4, 0.4)))
# The block top is at z = 0.4 (it starts 2 mm higher); a ball of radius 0.1 centered 5 cm
# above the top cuts 5 cm deep into the block.
machine.add(Ball(center=(0, 0, block.top_center.z + 0.05), radius=0.1))
