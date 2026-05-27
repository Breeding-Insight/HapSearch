"""Variant Annotation Module

Automatically detects and annotates SNPs and indels from multiple sequence alignments
"""

from Bio import AlignIO
from Bio.Align import MultipleSeqAlignment
from collections import Counter
import pandas as pd
from typing import List, Dict, Optional


class VariantAnnotator:
    """Detect and annotate SNPs and indels from MSA"""

    def __init__(self, min_frequency: float = 0.0, min_coverage: int = 2):
        """
        Initialize variant annotator

        Args:
            min_frequency: Minimum allele frequency to report (0.0 - 1.0)
            min_coverage: Minimum number of sequences required at a position
        """
        self.min_frequency = min_frequency
        self.min_coverage = min_coverage

    def annotate_alignment(self, alignment: MultipleSeqAlignment) -> List[Dict]:
        """
        Find all variants in alignment

        Args:
            alignment: BioPython MultipleSeqAlignment object

        Returns:
            List of variant dictionaries with position, type, frequencies, etc.
        """
        variants = []

        for i in range(alignment.get_alignment_length()):
            column = alignment[:, i]
            variant = self._analyze_column(i, column)

            if variant:
                variants.append(variant)

        return variants

    def _analyze_column(self, position: int, column: str) -> Optional[Dict]:
        """
        Analyze single alignment column for variants

        Args:
            position: 0-based position in alignment
            column: String of bases at this position

        Returns:
            Variant dictionary or None if not polymorphic
        """
        # Count all bases including gaps
        all_bases = Counter(column.upper())

        # Count non-gap bases
        bases_only = Counter([b for b in column.upper() if b != '-'])
        gap_count = all_bases.get('-', 0)
        total = len(column)

        # Skip if not enough coverage
        if len(column) < self.min_coverage:
            return None

        # Check if polymorphic (more than one non-gap base type OR has gaps)
        if len(bases_only) < 2 and gap_count == 0:
            return None  # Monomorphic, no variant

        # Determine variant type
        variant_type = 'INDEL' if gap_count > 0 else 'SNP'

        # Get reference (most common non-gap base)
        if bases_only:
            reference = bases_only.most_common(1)[0][0]
            alternates = [b for b in bases_only.keys() if b != reference]
        else:
            reference = None
            alternates = []

        # Calculate frequencies
        frequencies = {
            base: count / total
            for base, count in all_bases.items()
        }

        # Filter by minimum frequency
        significant_variants = [
            base for base, freq in frequencies.items()
            if freq >= self.min_frequency and base != reference
        ]

        if not significant_variants and gap_count == 0:
            return None

        # Classify SNP subtype
        subtype = None
        if variant_type == 'SNP':
            subtype = self._classify_snp(reference, alternates)
        elif variant_type == 'INDEL':
            subtype = self._classify_indel(gap_count, total)

        return {
            'position': position + 1,  # 1-indexed for display
            'position_0based': position,  # Keep 0-based for programming
            'type': variant_type,
            'subtype': subtype,
            'reference': reference,
            'alternates': alternates,
            'frequencies': frequencies,
            'gap_count': gap_count,
            'gap_frequency': gap_count / total,
            'column': column,
            'total_seqs': total
        }

    def _classify_snp(self, reference: str, alternates: List[str]) -> str:
        """
        Classify SNP as transition or transversion

        Args:
            reference: Reference base
            alternates: List of alternate bases

        Returns:
            'TRANSITION', 'TRANSVERSION', or 'MULTI-ALLELIC'
        """
        if not alternates:
            return None

        # Define transitions (purine-purine or pyrimidine-pyrimidine)
        transitions = [
            ('A', 'G'), ('G', 'A'),  # Purines
            ('C', 'T'), ('T', 'C')   # Pyrimidines
        ]

        if len(alternates) > 1:
            return 'MULTI-ALLELIC'

        for alt in alternates:
            if (reference, alt) in transitions:
                return 'TRANSITION'

        return 'TRANSVERSION'

    def _classify_indel(self, gap_count: int, total: int) -> str:
        """
        Classify indel as insertion or deletion

        Args:
            gap_count: Number of gaps in column
            total: Total sequences

        Returns:
            'INSERTION' or 'DELETION'
        """
        # If most sequences have gaps, it's likely an insertion in the reference
        if gap_count > total / 2:
            return 'INSERTION'
        else:
            return 'DELETION'

    def export_variants_dataframe(self, variants: List[Dict]) -> pd.DataFrame:
        """
        Convert variants to pandas DataFrame for display

        Args:
            variants: List of variant dictionaries

        Returns:
            pandas DataFrame
        """
        if not variants:
            return pd.DataFrame(columns=[
                'Position', 'Type', 'Subtype', 'Reference',
                'Alternates', 'Gap_Frequency', 'Details'
            ])

        rows = []
        for v in variants:
            # Format alternates
            alt_str = ','.join(v.get('alternates', []))

            # Format frequencies for display
            freq_details = []
            for base, freq in v['frequencies'].items():
                if base != '-' and base != v.get('reference'):
                    freq_details.append(f"{base}:{freq:.2%}")

            row = {
                'Position': v['position'],
                'Type': v['type'],
                'Subtype': v.get('subtype', ''),
                'Reference': v.get('reference', ''),
                'Alternates': alt_str,
                'Gap_Frequency': f"{v['gap_frequency']:.2%}",
                'Details': ', '.join(freq_details) if freq_details else '-'
            }
            rows.append(row)

        return pd.DataFrame(rows)

    def export_vcf(self, variants: List[Dict], reference_id: str,
                   output_file: str, start_position: int = 1):
        """
        Export variants to VCF format

        Args:
            variants: List of variant dictionaries
            reference_id: Reference sequence identifier
            output_file: Output VCF file path
            start_position: Genomic start position offset
        """
        with open(output_file, 'w') as f:
            # VCF header
            f.write("##fileformat=VCFv4.2\n")
            f.write(f"##reference={reference_id}\n")
            f.write("##INFO=<ID=TYPE,Number=1,Type=String,Description=\"Variant type\">\n")
            f.write("##INFO=<ID=SUBTYPE,Number=1,Type=String,Description=\"Variant subtype\">\n")
            f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")

            # Variant lines
            for v in variants:
                chrom = reference_id
                pos = start_position + v['position_0based']
                id_val = '.'
                ref = v.get('reference', 'N')
                alt = ','.join(v.get('alternates', ['N']))
                qual = '.'
                filter_val = 'PASS'

                info_parts = [
                    f"TYPE={v['type']}",
                    f"SUBTYPE={v.get('subtype', 'NA')}"
                ]
                info = ';'.join(info_parts)

                f.write(f"{chrom}\t{pos}\t{id_val}\t{ref}\t{alt}\t{qual}\t{filter_val}\t{info}\n")

    def get_variant_summary(self, variants: List[Dict]) -> Dict:
        """
        Get summary statistics of detected variants

        Args:
            variants: List of variant dictionaries

        Returns:
            Dictionary with summary statistics
        """
        if not variants:
            return {
                'total_variants': 0,
                'snps': 0,
                'indels': 0,
                'transitions': 0,
                'transversions': 0,
                'ti_tv_ratio': 0.0
            }

        snps = [v for v in variants if v['type'] == 'SNP']
        indels = [v for v in variants if v['type'] == 'INDEL']

        transitions = [v for v in snps if v.get('subtype') == 'TRANSITION']
        transversions = [v for v in snps if v.get('subtype') == 'TRANSVERSION']

        ti_tv_ratio = len(transitions) / len(transversions) if transversions else 0.0

        return {
            'total_variants': len(variants),
            'snps': len(snps),
            'indels': len(indels),
            'transitions': len(transitions),
            'transversions': len(transversions),
            'ti_tv_ratio': ti_tv_ratio
        }

    def filter_variants(self, variants: List[Dict],
                       variant_type: Optional[str] = None,
                       min_frequency: Optional[float] = None) -> List[Dict]:
        """
        Filter variants by type and frequency

        Args:
            variants: List of variant dictionaries
            variant_type: Filter by 'SNP' or 'INDEL', None for all
            min_frequency: Minimum alternate allele frequency

        Returns:
            Filtered list of variants
        """
        filtered = variants

        if variant_type:
            filtered = [v for v in filtered if v['type'] == variant_type]

        if min_frequency is not None:
            filtered = [
                v for v in filtered
                if any(freq >= min_frequency
                      for base, freq in v['frequencies'].items()
                      if base != v.get('reference') and base != '-')
            ]

        return filtered
