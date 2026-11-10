"""End-to-end check that an incremental build stores what a full build stores.

Builds two small synthetic species from scratch, changes one, then compares an
incremental build (starting from the first database) with a full build of the
same inputs, table by table, with row ids replaced by the names they stand for.
Needs Rscript with pwalign, like the real build.
"""

import contextlib
import io
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from scripts import build_database  # noqa: E402
from scripts.align_microhaplotypes import AlignmentError, find_rscript  # noqa: E402


def _have_pwalign() -> bool:
    try:
        rscript = find_rscript()
    except AlignmentError:
        return False
    import subprocess
    return subprocess.run([rscript, "-e", "library(pwalign)"], capture_output=True).returncode == 0


BASES = "ACGT"


def _mutate(seq: str, rng: random.Random) -> str:
    seq = list(seq)
    for _ in range(rng.randint(1, 3)):
        seq[rng.randrange(len(seq))] = rng.choice(BASES)
    if rng.random() < 0.4:  # an indel, so alignments have gaps
        pos = rng.randrange(5, len(seq) - 5)
        if rng.random() < 0.5:
            del seq[pos:pos + rng.randint(1, 3)]
        else:
            seq[pos:pos] = rng.choice(BASES) * rng.randint(1, 3)
    return "".join(seq)


def make_repo(root, *, species, common, chrom, token, samples_prefix, project_code,
              owner, seed, markers=6, extra_sample_file=False):
    """Write a minimal data repository in the layout manifest.toml expects."""
    rng = random.Random(seed)
    hap = os.path.join(root, "data", "hapSearch")
    os.makedirs(os.path.join(hap, "sample_hapStatus"))
    os.makedirs(os.path.join(hap, "hapPA"))
    os.makedirs(os.path.join(root, "data", "versions"))
    db = f"{common.lower()}_allele_db"

    alleles = []  # (allele id, sequence)
    for m in range(markers):
        marker = f"{chrom}_{(m + 1) * 1000:09d}"
        ref = "".join(rng.choice(BASES) for _ in range(60))
        alleles.append((f"{marker}|Ref_0001", ref))
        alleles.append((f"{marker}|Alt_0002", _mutate(ref, rng)))
        for k in range(rng.randint(1, 3)):
            alleles.append((f"{marker}|AltMatch_{k + 1:04d}", _mutate(ref, rng)))
    with open(os.path.join(root, "data", "versions", f"{db}_v001.fa"), "w") as fa:
        for name, seq in alleles:
            fa.write(f">{name}\n{seq}\n")
    with open(os.path.join(hap, "probes.botloci"), "w") as bot:
        for m in range(0, markers, 2):
            bot.write(f"{chrom}_{(m + 1) * 1000:09d}\n")

    def sample_file(path, names):
        with open(path, "w") as out:
            out.write("AlleleID," + ",".join(names) + "\n")
            for name, _ in alleles:
                out.write(name + "," + ",".join(str(rng.randint(0, 1)) for _ in names) + "\n")

    sample_file(os.path.join(hap, "sample_hapStatus", f"{token}-0001_MADC_hapStatus.csv"),
                [f"{samples_prefix}{i}" for i in range(1, 9)])
    tokens = [f"{token}-0001"]
    if extra_sample_file:
        sample_file(os.path.join(hap, "sample_hapStatus", f"{token}-0002_MADC_hapStatus.csv"),
                    [f"{samples_prefix}{i}" for i in range(20, 26)])
        tokens.append(f"{token}-0002")

    with open(os.path.join(hap, "HapSearch_mapping.csv"), "w") as mapping:
        mapping.write("genotyping_source,project_code,owner_name,project_name,description\n")
        for i, tok in enumerate(tokens):
            mapping.write(f"{tok},{project_code}_{i}_{tok},{owner},Plates {i},Test plates\n")
    with open(os.path.join(hap, "HapSearch_owner_contacts.csv"), "w") as contacts:
        contacts.write("Full Name,Species,First Name,Last Name,Primary Email,Alternate Email,"
                       "ORCiD,Employer,Position,Primary Location,Secondary Location(s)\n")
        first, last = owner.split()
        contacts.write(f"{owner},{common},{first},{last},{first.lower()}@example.org,,,"
                       "Example University,Breeder,Somewhere,\n")
    codes = [f"{project_code}_{i}_{tok}" for i, tok in enumerate(tokens)]
    with open(os.path.join(hap, "hapPA", f"{db}_v001_hapPA_matrix.csv"), "w") as pa:
        pa.write("AlleleID,CloneID," + ",".join(codes) + ",Presence_count\n")
        for name, _ in alleles:
            calls = [rng.randint(0, 1) for _ in codes]
            pa.write(f"{name},{name.split('|')[0]}," + ",".join(map(str, calls)) + f",{sum(calls)}\n")

    with open(os.path.join(hap, "manifest.toml"), "w") as manifest:
        manifest.write(f"""
[metadata]
project_mapping = "HapSearch_mapping.csv"
owner_contacts = "HapSearch_owner_contacts.csv"

[[species]]
name = "{species}"
common_name = "{common}"
fasta = "/data/versions/{db}_{{version}}.fa"
botloci = "*.botloci"
sample_presence = "sample_hapStatus"
project_presence = "hapPA/{{fasta}}_hapPA_matrix.csv"
""")
    return root


def canonical(db_path):
    """Every stored row, with ids replaced by the names they stand for."""
    import numpy as np

    conn = sqlite3.connect(db_path)
    q = lambda sql: sorted(tuple(r) for r in conn.execute(sql).fetchall())  # noqa: E731
    mh_name = dict(conn.execute("SELECT id, haplotype_name FROM microhaplotypes"))
    out = {
        "species": q("SELECT name, common_name, description FROM species"),
        "chromosomes": q("SELECT s.name, c.chromosome_name, c.length, c.microhaplotype_count "
                         "FROM chromosomes c JOIN species s ON s.id = c.species_id"),
        "markers": q("SELECT mk.marker_id, c.chromosome_name, mk.position_start, mk.position_end, "
                     "mk.marker_type, mk.description FROM markers mk "
                     "JOIN chromosomes c ON c.id = mk.chromosome_id"),
        "microhaplotypes": q("SELECT m.haplotype_name, m.haplotype_sequence, m.frequency, "
                             "m.sample_count, mk.marker_id FROM microhaplotypes m "
                             "JOIN markers mk ON mk.id = m.marker_id"),
        "botloci": q("SELECT marker_id FROM botloci"),
        "projects": q("SELECT project_code, project_name, pi_name, pi_email, pi_institution, "
                      "pi_department, description, start_date FROM projects"),
        "samples": q("SELECT sa.sample_code, p.project_code, s.name, sa.sample_type FROM samples sa "
                     "JOIN projects p ON p.id = sa.project_id JOIN species s ON s.id = sa.species_id"),
        "contacts": q("SELECT full_name, email, institution, department, location FROM contacts"),
        "project_contacts": q("SELECT p.project_code, c.full_name, pc.role FROM project_contacts pc "
                              "JOIN projects p ON p.id = pc.project_id "
                              "JOIN contacts c ON c.id = pc.contact_id"),
        "alignments": q("SELECT m.haplotype_name, r.haplotype_name, a.aligned_reference, "
                        "a.aligned_sequence, a.score FROM microhaplotype_alignments a "
                        "JOIN microhaplotypes m ON m.id = a.microhaplotype_id "
                        "JOIN microhaplotypes r ON r.id = a.reference_id"),
    }
    entity_name = {}
    entity_name.update({("sample", i): c for i, c in conn.execute("SELECT id, sample_code FROM samples")})
    entity_name.update({("project", i): c for i, c in conn.execute("SELECT id, project_code FROM projects")})
    artifacts, artifact_key = [], {}
    for row in conn.execute(
        "SELECT pa.id, pa.entity_type, s.name, p.project_code, pa.source_path, pa.source_sha256, "
        "pa.compression, pa.schema_version, pa.microhaplotype_count, pa.entity_count, "
        "pa.presence_count, pa.artifact_size_bytes, pa.microhaplotype_ids FROM presence_artifacts pa "
        "LEFT JOIN species s ON s.id = pa.species_id LEFT JOIN projects p ON p.id = pa.project_id"
    ):
        key = (row[1], os.path.basename(row[4]))
        artifact_key[row[0]] = key
        ids = np.frombuffer(row[12], dtype="<i8")
        artifacts.append((*key, row[2], row[3], *row[5:12], tuple(mh_name[int(i)] for i in ids)))
    out["presence_artifacts"] = sorted(artifacts)
    out["presence_bitmaps"] = sorted(
        (artifact_key[a], r, entity_name[(artifact_key[a][0], e)], n, bytes(b))
        for a, r, e, n, b in conn.execute(
            "SELECT artifact_id, row_index, entity_id, present_count, packed_presence FROM presence_bitmaps")
    )
    out["presence_summary"] = sorted(
        (mh_name[m], s, t, p, tot, round(f, 12), artifact_key.get(a))
        for m, s, t, p, tot, f, a in conn.execute(
            "SELECT ps.microhaplotype_id, sp.name, ps.entity_type, ps.present_count, ps.total_count, "
            "ps.frequency, ps.artifact_id FROM microhaplotype_presence_summary ps "
            "JOIN species sp ON sp.id = ps.species_id")
    )
    conn.close()
    return out


@unittest.skipUnless(_have_pwalign(), "needs Rscript with pwalign")
class IncrementalBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hapsearch-incremental-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def repo(self, name, **kwargs):
        path = os.path.join(self.tmp, "repos", name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        return make_repo(path, **kwargs)

    def alfalfa(self, **extra):
        return self.repo("alfalfa", species="Medicago testiva", common="Alfalfa", chrom="chrA",
                         token="DAl90", samples_prefix="AL", project_code="PA", owner="Ann Lee",
                         seed=1, **extra)

    def pecan(self, **extra):
        defaults = dict(species="Carya testensis", common="Pecan", chrom="ChrP", token="DPec90",
                        samples_prefix="PE", project_code="PP", owner="Pat Kim", seed=2)
        defaults.update(extra)
        return self.repo("pecan", **defaults)

    def build(self, name, repos, reuse=None):
        output = os.path.join(self.tmp, f"{name}.db")
        sources = [build_database.local_source(path) for path in repos]
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            ok = build_database.build(sources, output, None, os.path.join(self.tmp, "cache"),
                                      reuse_from=reuse)
        self.assertTrue(ok, log.getvalue()[-3000:])
        return output, log.getvalue()

    def test_incremental_build_matches_full_build(self):
        alfalfa, pecan = self.alfalfa(), self.pecan()
        first, log = self.build("first", [alfalfa, pecan])
        self.assertIn("from scratch", log)

        # Nothing changed: everything is kept and nothing is aligned again.
        same, log = self.build("same", [alfalfa, pecan], reuse=first)
        self.assertIn("Changed, rebuilt: none", log)
        self.assertIn("No microhaplotypes need aligning", log)
        self.assertEqual(canonical(same), canonical(first))

        # Pecan gains a sample file and different sequences.
        pecan = self.pecan(seed=3, markers=7, extra_sample_file=True)
        incremental, log = self.build("incremental", [alfalfa, pecan], reuse=first)
        self.assertIn("Unchanged, kept: Medicago testiva", log)
        self.assertIn("Changed, rebuilt: Carya testensis", log)
        full, _ = self.build("full", [alfalfa, pecan])
        self.assertEqual(canonical(incremental), canonical(full))
        # The comparison sees real differences: pecan's rows did change, and
        # every table holds rows.
        before, after = canonical(first), canonical(incremental)
        self.assertNotEqual(before["microhaplotypes"], after["microhaplotypes"])
        self.assertNotEqual(before["presence_bitmaps"], after["presence_bitmaps"])
        self.assertTrue(all(after.values()), [t for t, rows in after.items() if not rows])

    def test_removed_species_is_deleted(self):
        alfalfa, pecan = self.alfalfa(), self.pecan()
        first, _ = self.build("first", [alfalfa, pecan])
        only_alfalfa, log = self.build("only_alfalfa", [alfalfa], reuse=first)
        self.assertIn("No longer listed, deleted: Carya testensis", log)
        full, _ = self.build("full", [alfalfa])
        self.assertEqual(canonical(only_alfalfa), canonical(full))

    def test_shared_sample_names_fall_back_to_a_full_build(self):
        alfalfa = self.alfalfa()
        pecan = self.pecan(samples_prefix="AL")  # same sample names as alfalfa
        first, _ = self.build("first", [alfalfa, pecan])
        pecan = self.pecan(samples_prefix="AL", seed=3)
        rebuilt, log = self.build("rebuilt", [alfalfa, pecan], reuse=first)
        self.assertIn("Building every species from scratch instead", log)
        self.assertIn("share the sample name", log)
        full, _ = self.build("full", [alfalfa, pecan])
        self.assertEqual(canonical(rebuilt), canonical(full))


if __name__ == "__main__":
    unittest.main()
