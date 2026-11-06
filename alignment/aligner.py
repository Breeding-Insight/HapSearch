"""Stack the stored BIGr alignments of a locus's microhaplotypes into one alignment.

Each microhaplotype's alignment to its locus's Ref_0001 is computed by the
database build in R, with BIGr's settings (scripts/align_microhaplotypes.R).
"""

from typing import List

from Bio.Align import MultipleSeqAlignment
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord


def merge_reference_alignments(reference: SeqRecord, pairwise: List[tuple],
                               pad_toward_start: bool = False) -> MultipleSeqAlignment:
    """
    Stack pairwise alignments to one reference into a single alignment.

    Each sequence keeps exactly the alignment it was given, so its variants
    are relative to the reference. Bases a sequence inserts relative to the
    reference get their own columns; the other rows are gapped there.

    Args:
        reference: The reference record
        pairwise: (record_id, aligned_reference, aligned_sequence) for each
            other sequence, both rows gapped and the same length
        pad_toward_start: Right-align inserted bases within their columns
            (gaps first) instead of left-aligning them

    Returns:
        MultipleSeqAlignment with the reference first
    """
    ref_seq = str(reference.seq).upper()

    # For each sequence: the base (or '-') aligned to each reference base,
    # and the bases inserted before each reference base (slot len(ref) = after the last).
    per_record = []
    for record_id, ref_row, seq_row in pairwise:
        if ref_row.replace('-', '').upper() != ref_seq:
            raise ValueError(f"Alignment for {record_id} is not against {reference.id}")
        aligned = []
        inserts = [''] * (len(ref_seq) + 1)
        for ref_char, seq_char in zip(ref_row.upper(), seq_row.upper()):
            if ref_char == '-':
                inserts[len(aligned)] += seq_char
            else:
                aligned.append(seq_char)
        per_record.append((record_id, aligned, inserts))

    slot_widths = [
        max((len(inserts[slot]) for _, _, inserts in per_record), default=0)
        for slot in range(len(ref_seq) + 1)
    ]

    def pad(insert, width):
        return insert.rjust(width, '-') if pad_toward_start else insert.ljust(width, '-')

    def build_row(aligned, inserts):
        parts = []
        for slot in range(len(ref_seq) + 1):
            parts.append(pad(inserts[slot], slot_widths[slot]))
            if slot < len(ref_seq):
                parts.append(aligned[slot])
        return ''.join(parts)

    rows = [SeqRecord(Seq(build_row(list(ref_seq), [''] * (len(ref_seq) + 1))),
                      id=reference.id, description="")]
    for record_id, aligned, inserts in per_record:
        rows.append(SeqRecord(Seq(build_row(aligned, inserts)), id=record_id, description=""))
    return MultipleSeqAlignment(rows)


_COMPLEMENT = str.maketrans('ACGTMRWSYKVHDBNacgtmrwsykvhdbn', 'TGCAKYWSRMBDHVNtgcakywsrmbdhvn')


def reverse_complement_row(row: str) -> str:
    """Reverse complement a gapped alignment row; gaps stay gaps."""
    return row.translate(_COMPLEMENT)[::-1]
