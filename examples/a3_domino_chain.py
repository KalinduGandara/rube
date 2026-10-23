"""Acceptance scenario A3: a straight chain of 20 dominoes started by tilting the first one.

Expected (``rube run``): all 20 dominoes ``fell_over``, and their ``fell_over`` event frames
strictly increase along the chain (each domino falls after the one before it).
"""

from rube import Machine, domino_chain

machine = Machine(name="a3_domino_chain", duration=8)

# 20 dominoes 0.4 m apart (half their 0.8 m height) along a 7.6 m line; the first one is
# pre-tilted 10 degrees so it falls on its own and starts the chain.
chain = machine.add(domino_chain([(-3.8, 0, 0), (3.8, 0, 0)], count=20, tilt_first_deg=10))
