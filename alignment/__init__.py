"""Multiple Sequence Alignment Module

Provides alignment and variant annotation functionality for Haplosearch
"""

from .aligner import merge_reference_alignments, reverse_complement_row
from .variant_annotator import VariantAnnotator

__all__ = ['merge_reference_alignments', 'reverse_complement_row', 'VariantAnnotator']
