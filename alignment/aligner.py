"""Multiple Sequence Alignment Engine

Provides CLUSTAL Omega alignment for microhaplotype sequences
"""

from Bio import SeqIO, AlignIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment
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
