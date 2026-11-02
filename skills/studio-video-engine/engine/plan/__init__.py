"""``jjv plan explain`` (T-E45 P0): what will a change re-render, and what does it cost -- before anything renders.

CPU-only and read-only: it reads two versions of the episode inputs (a review config, the mix plan, optional GPU
core declarations), computes a ``node_key`` per stage node, marks CHANGED / UNCHANGED, propagates to dependants and
prices every changed node from a measured cost table (``recipes/plan/costs-v001.json``).  It never submits a job:
a changed GPU node is printed as "needs approval" and is never executed (spec T-E45 2.2 / 2.3).
"""
