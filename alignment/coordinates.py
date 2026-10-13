"""Coordinate helpers for MSA visualizations."""

from typing import Iterable, List, Optional

MSA_AXIS_TICK_FONT = {
    "family": "Arial, sans-serif",
    "size": 11,
    "color": "#111111",
}

MSA_AXIS_TITLE_FONT = {
    "family": "Arial, sans-serif",
    "size": 13,
    "color": "#111111",
}


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


def amplicon_strand_label(is_bottom_strand: bool) -> str:
    """Return chart-visible amplicon strand text."""
    strand = "bottom" if is_bottom_strand else "top"
    return f"Amplicon is on the {strand} strand"


def msa_chart_title(marker_id: str, is_bottom_strand: bool = False) -> str:
    """Build the MSA chart title without chromosome coordinate ranges."""
    return (
        "<b>Multiple Sequence Alignment</b><br>"
        f"<sup>Marker: {marker_id}<br>"
        f"{amplicon_strand_label(is_bottom_strand)}</sup>"
    )
