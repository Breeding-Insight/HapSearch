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

# Bottom-strand loci are reverse complemented all at once.
bottom <- pairs$bottom == "1"
if (any(bottom)) {
  pairs$reference[bottom] <- as.character(reverseComplement(DNAStringSet(pairs$reference[bottom])))
  pairs$sequence[bottom] <- as.character(reverseComplement(DNAStringSet(pairs$sequence[bottom])))
}

gaps <- function(k) strrep("-", k)

# The aligned strings, as as.character(alignedPattern(a)) and
# as.character(alignedSubject(a)) give them. Those two calls took ~90% of the
# run time, so the strings are rebuilt from aligned(), which leaves out the
# end gaps, plus each sequence's unaligned ends (pattern's before subject's).
aligned_strings <- function(a, ref, seq) {
  pa <- pattern(a); sa <- subject(a)
  ps <- start(pa); pe <- end(pa); ss <- start(sa); se <- end(sa)
  np <- nchar(ref); ns <- nchar(seq)
  c(paste0(substr(ref, 1, ps - 1), gaps(ss - 1), as.character(aligned(pa)),
           substr(ref, pe + 1, np), gaps(ns - se)),
    paste0(gaps(ps - 1), substr(seq, 1, ss - 1), as.character(aligned(sa)),
           gaps(np - pe), substr(seq, se + 1, ns)))
}

align_one <- function(i) {
  ref <- pairs$reference[i]
  seq <- pairs$sequence[i]
  a <- pairwiseAlignment(ref, seq, substitutionMatrix = sigma,
                         gapOpening = -1.4, gapExtension = -0.1, type = "global")
  c(pairs$microhaplotype_id[i], aligned_strings(a, ref, seq), format(score(a), digits = 15))
}

# Align in chunks so the build log shows progress; each pair is aligned
# exactly as before, so chunking does not change any result.
chunk_size <- 2000L
total <- nrow(pairs)
rows <- list()
for (start in seq(1L, max(total, 1L), by = chunk_size)) {
  if (!total) break
  idx <- start:min(start + chunk_size - 1L, total)
  chunk <- if (.Platform$OS.type == "unix" && cores > 1) {
    mclapply(idx, align_one, mc.cores = cores)
  } else {
    lapply(idx, align_one)
  }
  rows <- c(rows, chunk)
  cat(sprintf("  aligned %d of %d\n", max(idx), total))
  flush(stdout())
}
failed <- vapply(rows, inherits, logical(1), what = "try-error")
if (any(failed)) stop("Alignment failed for ", sum(failed), " sequence(s): ", rows[failed][[1]])

out <- if (length(rows)) do.call(rbind, rows) else matrix(character(0), ncol = 4)
colnames(out) <- c("microhaplotype_id", "aligned_reference", "aligned_sequence", "score")
write.table(out, args[2], sep = "\t", quote = FALSE, row.names = FALSE)
cat(sprintf("Aligned %d microhaplotypes to their Ref_0001 on %d core(s)\n", nrow(out), cores))
