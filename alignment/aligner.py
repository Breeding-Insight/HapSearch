"""Multiple Sequence Alignment Engine

Provides CLUSTAL Omega alignment and reference-anchored alignment for
microhaplotype sequences
"""

from Bio import SeqIO, AlignIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment, PairwiseAligner
import tempfile
import os
from typing import List, Union
import io


class MSAAligner:
    """Multiple Sequence Alignment handler with CLUSTAL Omega support"""

    def __init__(self, algorithm='clustal'):
        """
        Initialize aligner

        Args:
            algorithm: Default algorithm (only 'clustal' is supported)
        """
        if algorithm != 'clustal':
            raise ValueError("Only 'clustal' algorithm is supported")
        self.algorithm = algorithm

    def align_sequences(self, sequences: Union[str, List[SeqRecord]],
                       algorithm: str = None) -> MultipleSeqAlignment:
        """
        Align sequences using CLUSTAL Omega

        Args:
            sequences: List of SeqRecord objects, FASTA file path, or FASTA string
            algorithm: Must be 'clustal' (overrides default)

        Returns:
            MultipleSeqAlignment object
        """
        alg = algorithm or self.algorithm

        if alg != 'clustal':
            raise ValueError(f"Only 'clustal' algorithm is supported, got: {alg}")

        return self._align_clustal(sequences)

    def align_to_reference(self, sequences, reference_id: str,
                           gaps_toward_end: bool = False) -> MultipleSeqAlignment:
        """
        Align every sequence to one reference and merge the results.

        Each sequence is aligned to the reference on its own, so its variants
        are always relative to the reference rather than to the other
        sequences. Gaps inside a repeat run (e.g. one A missing from AAAA) are
        slid to one end of the run so equivalent indels share a column.

        Args:
            sequences: Input sequences in various formats (must include the reference)
            reference_id: ID of the reference record
            gaps_toward_end: Slide gaps toward the end of the sequence instead
                of the start. For a bottom-strand amplicon the end is the
                lowest genome coordinate, matching VCF left-normalization.

        Returns:
            MultipleSeqAlignment with the reference first
        """
        seq_records = self._parse_sequences(sequences)
        if len(seq_records) < 2:
            raise ValueError("At least 2 sequences required for alignment")

        reference = next((r for r in seq_records if r.id == reference_id), None)
        if reference is None:
            raise ValueError(f"Reference {reference_id!r} not found")
        ref_seq = str(reference.seq).upper()
        others = [r for r in seq_records if r is not reference]

        aligner = PairwiseAligner()
        aligner.mode = 'global'
        aligner.match_score = 2
        aligner.mismatch_score = -3
        aligner.open_gap_score = -5
        aligner.extend_gap_score = -2
        # Alleles can be truncated relative to the reference.
        aligner.end_gap_score = 0

        # For each allele: the base (or '-') aligned to each reference base,
        # and the bases inserted before each reference base (slot len(ref) = after the last).
        per_record = []
        for record in others:
            seq = str(record.seq).upper()
            ref_row, seq_row = _pairwise_rows(aligner, ref_seq, seq)
            ref_row, seq_row = _normalize_gaps(ref_row, seq_row, gaps_toward_end)
            aligned = []
            inserts = [''] * (len(ref_seq) + 1)
            for ref_char, seq_char in zip(ref_row, seq_row):
                if ref_char == '-':
                    inserts[len(aligned)] += seq_char
                else:
                    aligned.append(seq_char)
            per_record.append((record, aligned, inserts))

        slot_widths = [
            max((len(inserts[slot]) for _, _, inserts in per_record), default=0)
            for slot in range(len(ref_seq) + 1)
        ]

        def pad(insert, width):
            return insert.rjust(width, '-') if gaps_toward_end else insert.ljust(width, '-')

        def build_row(aligned, inserts):
            parts = []
            for slot in range(len(ref_seq) + 1):
                parts.append(pad(inserts[slot], slot_widths[slot]))
                if slot < len(ref_seq):
                    parts.append(aligned[slot])
            return ''.join(parts)

        rows = [SeqRecord(Seq(build_row(list(ref_seq), [''] * (len(ref_seq) + 1))),
                          id=reference.id, description="")]
        for record, aligned, inserts in per_record:
            rows.append(SeqRecord(Seq(build_row(aligned, inserts)), id=record.id, description=""))
        return MultipleSeqAlignment(rows)

    def _parse_sequences(self, sequences):
        """Parse sequences from various input formats"""
        if isinstance(sequences, str):
            # Check if it's a file path or FASTA content
            if os.path.exists(sequences):
                # File path
                with open(sequences) as f:
                    return list(SeqIO.parse(f, "fasta"))
            else:
                # FASTA string
                return list(SeqIO.parse(io.StringIO(sequences), "fasta"))
        elif isinstance(sequences, list):
            # List of SeqRecords
            return sequences
        else:
            raise ValueError("Sequences must be file path, FASTA string, or list of SeqRecords")

    def _align_clustal(self, sequences) -> MultipleSeqAlignment:
        """
        Use CLUSTAL Omega for alignment via command-line

        Args:
            sequences: Input sequences in various formats

        Returns:
            MultipleSeqAlignment object
        """
        import subprocess

        # Parse sequences
        seq_records = self._parse_sequences(sequences)

        if len(seq_records) < 2:
            raise ValueError("At least 2 sequences required for alignment")

        # Create temporary files
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fasta') as fin:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fasta') as fout:
                SeqIO.write(seq_records, fin, "fasta")
                fin_path = fin.name
                fout_path = fout.name

        try:
            # Run CLUSTAL Omega command
            # clustalo -i input.fasta -o output.fasta --auto --force
            result = subprocess.run(
                ['clustalo', '-i', fin_path, '-o', fout_path, '--auto', '--force'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"CLUSTAL Omega failed with error: {result.stderr}\n"
                    f"Make sure 'clustalo' is installed and in PATH"
                )

            # Read alignment
            alignment = AlignIO.read(fout_path, "fasta")
            return alignment

        except subprocess.TimeoutExpired:
            raise RuntimeError("CLUSTAL Omega alignment timed out after 5 minutes")
        except Exception as e:
            raise RuntimeError(
                f"CLUSTAL Omega failed: {str(e)}"
            )
        finally:
            os.unlink(fin_path)
            os.unlink(fout_path)

    def alignment_to_fasta(self, alignment: MultipleSeqAlignment) -> str:
        """
        Convert alignment to FASTA string

        Args:
            alignment: MultipleSeqAlignment object

        Returns:
            FASTA formatted string
        """
        output = io.StringIO()
        AlignIO.write(alignment, output, "fasta")
        return output.getvalue()

    def alignment_to_dict(self, alignment: MultipleSeqAlignment) -> List[dict]:
        """
        Convert alignment to dictionary format for Dash Bio

        Args:
            alignment: MultipleSeqAlignment object

        Returns:
            List of dicts with 'label' and 'sequence' keys
        """
        return [
            {
                'label': record.id,
                'sequence': str(record.seq)
            }
            for record in alignment
        ]

    @staticmethod
    def fasta_to_dict(fasta_content: str) -> List[dict]:
        """
        Convert FASTA string to dictionary format

        Args:
            fasta_content: FASTA formatted string

        Returns:
            List of dicts with 'label' and 'sequence' keys
        """
        records = SeqIO.parse(io.StringIO(fasta_content), "fasta")
        return [
            {
                'label': record.id,
                'sequence': str(record.seq)
            }
            for record in records
        ]


def _pairwise_rows(aligner: PairwiseAligner, ref_seq: str, seq: str):
    """Return the gapped reference and sequence rows of the best alignment."""
    alignment = aligner.align(ref_seq, seq)[0]
    ref_row, seq_row = [], []
    (ref_blocks, seq_blocks) = alignment.aligned
    ref_pos = seq_pos = 0
    for (ref_start, ref_end), (seq_start, seq_end) in zip(ref_blocks, seq_blocks):
        # Unaligned stretches before this block are gaps in the other row.
        ref_row.append(ref_seq[ref_pos:ref_start]); seq_row.append('-' * (ref_start - ref_pos))
        ref_row.append('-' * (seq_start - seq_pos)); seq_row.append(seq[seq_pos:seq_start])
        ref_row.append(ref_seq[ref_start:ref_end]); seq_row.append(seq[seq_start:seq_end])
        ref_pos, seq_pos = ref_end, seq_end
    ref_row.append(ref_seq[ref_pos:]); seq_row.append('-' * (len(ref_seq) - ref_pos))
    ref_row.append('-' * (len(seq) - seq_pos)); seq_row.append(seq[seq_pos:])
    return ''.join(ref_row), ''.join(seq_row)


def _normalize_gaps(top: str, bottom: str, toward_end: bool):
    """Slide each gap run as far as it goes toward one end without changing the score.

    A gap over bases B[s:e] can move one step toward the end when B[s] == B[e]
    (the run rotates), and toward the start when B[s-1] == B[e-1].
    """
    rows = [list(top), list(bottom)]
    length = len(top)
    changed = True
    while changed:
        changed = False
        for gapped, other in ((0, 1), (1, 0)):
            g, o = rows[gapped], rows[other]
            col = 0
            while col < length:
                if g[col] != '-':
                    col += 1
                    continue
                start = col
                while col < length and g[col] == '-':
                    col += 1
                end = col
                # Gaps at either end only mark a truncated sequence; leave them.
                if start == 0 or end == length:
                    continue
                if toward_end:
                    while (end < length and g[end] != '-' and o[end] != '-'
                           and o[start] != '-' and o[start] == o[end]):
                        g[start], g[end] = g[end], '-'
                        start += 1
                        end += 1
                        changed = True
                    col = end
                else:
                    while (start > 0 and g[start - 1] != '-' and o[start - 1] != '-'
                           and o[end - 1] != '-' and o[start - 1] == o[end - 1]):
                        g[end - 1], g[start - 1] = g[start - 1], '-'
                        start -= 1
                        end -= 1
                        changed = True
    return ''.join(rows[0]), ''.join(rows[1])
