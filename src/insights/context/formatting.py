"""Formatting shared by role inference and prompt rendering.

Small, but it lives in one place because a number that is rounded one way in a
role's evidence and another way in the prompt is a contradiction the reader has
to resolve.
"""

from __future__ import annotations


def percent(rate: float) -> str:
    """A rate as a percentage, without rounding away the thing that matters.

    A column that is 99.8% empty must not print as "100% empty" next to five
    example values: the reader would take that as a contradiction, and a
    language model would take it as permission to ignore one of the two. The
    same applies at the bottom of the range.
    """
    if rate <= 0.0:
        return "0%"
    if rate >= 1.0:
        return "100%"
    if rate < 0.005:
        return "<1%"
    if rate > 0.995:
        return ">99%"
    return f"{rate * 100:.0f}%"
