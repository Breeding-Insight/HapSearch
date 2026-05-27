"""Multiple Sequence Alignment Module

Provides alignment and variant annotation functionality for Haplosearch
"""

from .aligner import MSAAligner
from .variant_annotator import VariantAnnotator

__all__ = ['MSAAligner', 'VariantAnnotator']
