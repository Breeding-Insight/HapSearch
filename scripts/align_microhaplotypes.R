# Align every microhaplotype to its locus's Ref_0001 exactly as BIGr does.
#
# The settings are copied from compare() in BIGr's R/madc2vcf_all.R (v0.7.2),
# the alignment BIGapp's MADC-to-VCF uses: bottom-strand loci are reverse
# complemented first, then each sequence is globally aligned to the Ref with
# pwalign::pairwiseAlignment(ref, sequence, ...), Ref as the pattern.
#
# Usage: Rscript scripts/align_microhaplotypes.R <input.tsv> <output.tsv> [cores]
#
# Input (tab-separated, with header): microhaplotype_id, bottom (0/1),
# reference, sequence. Output (tab-separated, with header): microhaplotype_id,
# aligned_reference, aligned_sequence, score, all in BIGr's orientation
# (reverse complemented for bottom-strand loci).

suppressPackageStartupMessages({
  library(Biostrings)
  library(pwalign)
  library(parallel)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("Usage: align_microhaplotypes.R <input.tsv> <output.tsv> [cores]")
cores <- if (length(args) >= 3) as.integer(args[3]) else max(1L, detectCores())

pairs <- read.delim(args[1], colClasses = "character", quote = "", na.strings = character(0))
sigma <- nucleotideSubstitutionMatrix(match = 1, mismatch = -0.5, baseOnly = FALSE)

align_one <- function(i) {
  ref <- pairs$reference[i]
  seq <- pairs$sequence[i]
  if (pairs$bottom[i] == "1") {
    ref <- as.character(reverseComplement(DNAString(ref)))
    seq <- as.character(reverseComplement(DNAString(seq)))
  }
  a <- pairwiseAlignment(ref, seq, substitutionMatrix = sigma,
                         gapOpening = -1.4, gapExtension = -0.1, type = "global")
  c(pairs$microhaplotype_id[i], as.character(alignedPattern(a)),
    as.character(alignedSubject(a)), format(score(a), digits = 15))
}

rows <- if (nrow(pairs)) {
  if (.Platform$OS.type == "unix" && cores > 1) {
    mclapply(seq_len(nrow(pairs)), align_one, mc.cores = cores)
  } else {
    lapply(seq_len(nrow(pairs)), align_one)
  }
} else list()
failed <- vapply(rows, inherits, logical(1), what = "try-error")
if (any(failed)) stop("Alignment failed for ", sum(failed), " sequence(s): ", rows[failed][[1]])

out <- if (length(rows)) do.call(rbind, rows) else matrix(character(0), ncol = 4)
colnames(out) <- c("microhaplotype_id", "aligned_reference", "aligned_sequence", "score")
write.table(out, args[2], sep = "\t", quote = FALSE, row.names = FALSE)
cat(sprintf("Aligned %d microhaplotypes to their Ref_0001 on %d core(s)\n", nrow(out), cores))
