"""Forensic reconstruction candidate for the missing Sentinel breadth classifier.

IMPORTANT:
- GREEN is high-confidence reconstruction, not certified source.
- DAMAGED_CORE is a proven lower-bound component of the original damaged/amber
  classifier. It is NOT a complete replacement for the missing original function.
"""

def reconstructed_green(row):
    return (
        row.own_dd >= -0.075
        and row.r21 >= 0.0
        and row.r63 >= 0.0
    )

def reconstructed_damaged_core(row):
    return (
        row.own_dd <= -0.10
        or row.r21 <= -0.03
    )

# Original downstream semantics recovered from retained source:
# damaged_breadth = mean(x.amber)
# green_breadth   = mean(x.green)
#
# The original x.amber contained an additional escalation term that has not yet
# been uniquely identified from the retained artifacts. Do not silently equate
# reconstructed_damaged_core with certified damaged_breadth.
