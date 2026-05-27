"""Coordinate helpers for MSA visualizations."""

from typing import Iterable, List, Optional


def relative_position(
    position: float,
    target_position: Optional[float],
    is_bottom_strand: bool = False,
) -> float:
    """Convert an MSA x position to a target-SNP-relative position.

    Top-strand loci increase left-to-right, so positions before the target SNP
    are negative. Bottom-strand loci are displayed in the opposite orientation.
    """
    if target_position is None:
        return position

    if is_bottom_strand:
        return target_position - position
    return position - target_position


def relative_positions(
    positions: Iterable[float],
    target_position: Optional[float],
    is_bottom_strand: bool = False,
) -> List[float]:
    """Convert an iterable of x positions to target-SNP-relative positions."""
    return [
        relative_position(position, target_position, is_bottom_strand)
        for position in positions
    ]
