# Updating HapSearch data

HapSearch's database is rebuilt from scratch every time from the files in
[Breeding-Insight/alfalfa_haplotype_db](https://github.com/Breeding-Insight/alfalfa_haplotype_db).
Nobody edits the database directly. To add or change data, you change files in that
repository, then publish a new build.

## Where the inputs live

Everything HapSearch reads is listed in `{species}/data/hapSearch/manifest.toml` in the
data repository (copy [manifest.example.toml](manifest.example.toml) to start one):

```text
{species}/data/hapSearch/
  manifest.toml                  what goes into the database
  HapSearch_mapping.csv          genotyping source (DAl...) -> project
  HapSearch_owner_contacts.csv   project owners' contact details
  <probe design>.botloci         bottom-strand markers (optional)
  Sample_hapStatus/              one *_hapStatus.csv per genotyping order
  hapPA/                         *_hapPA_matrix.csv per FASTA version
```

The FASTA allele database stays where it already lives in that repository; the
manifest points at it with a path starting with `/` (the repository root).

Rules the build enforces:

- Every sample file name must contain its `DAl...` order number, and that number needs
  a row in `HapSearch_mapping.csv`. Every owner named there needs a row in
  `HapSearch_owner_contacts.csv`.
- The FASTA must be the version the presence calls were made against. If more than 2%
  of a matrix's alleles are missing from the FASTA, the build stops and says so.
- GitHub rejects files over 100 MB. Gzip large matrices (`gzip -k file.csv`, then commit
  `file.csv.gz` instead); the build reads them directly.

## Common changes

**New genotyping order:** add its `*_hapStatus.csv` to `Sample_hapStatus/`, add a row
for its `DAl...` number to `HapSearch_mapping.csv`, and add the owner to
`HapSearch_owner_contacts.csv` if they are new.

**New FASTA version:** commit the new FASTA, add the matching `*_hapPA_matrix.csv` to
`hapPA/`, and update `fasta` and `project_presence` in `manifest.toml` together.

**Correcting a file:** commit the corrected file. Git keeps every earlier version.

Commit the change, then tag the commit so the build can be pinned to it, for example:

```bash
git tag hapsearch-2026-10-13
git push origin main --tags
```

## Check the build on your computer (optional, recommended)

From the HapSearch app repository, with the data repository cloned next to it:

```bash
python scripts/build_database.py --data-repo ../alfalfa_haplotype_db
```

This takes about 3 minutes. It writes `data/hapsearch.db` only if every import and
check passes, and prints how many rows each table gained or lost compared with your
previous local build. Run the app locally to look at the result:

```bash
python app.py
```

## Publish

1. In the Google Cloud console, open **Cloud Build → Triggers**.
2. On the HapSearch trigger, click **Run**.
3. Set `_DATA_REF` to the tag you pushed (or leave it as `main` for the latest commit),
   and click **Run trigger**.

The pipeline ([cloudbuild.yaml](../cloudbuild.yaml)) clones the data repository at that
ref, builds and checks the database, builds the app image and deploys it. If anything
fails, nothing is deployed and the build log shows why. A successful run takes roughly
10 minutes; the new version is live as soon as it finishes, and the Cloud Run revision
records the data version in `HAPSEARCH_DATA_VERSION`.

The database itself records what it was built from in its `build_info` table
(build time, data repository commit, manifest checksum).

## Roll back

Cloud Run keeps earlier revisions. In **Cloud Run → hapsearch → Revisions**, choose the
previous revision and **Manage traffic → 100%**. Fix the data, then publish again.

## One-time setup (already done once per project)

- A Secret Manager secret `hapsearch-github-token` holding a GitHub fine-grained token
  with read-only **Contents** access to `Breeding-Insight/alfalfa_haplotype_db`, with
  `roles/secretmanager.secretAccessor` granted to the Cloud Build service account.
- A Cloud Build trigger on the HapSearch app repository using `cloudbuild.yaml`, with
  **manual** invocation and the substitutions `_DATA_REPO` and `_DATA_REF`.
- The Cloud Run service, Firestore database and service identity described in
  [cloud-run.md](cloud-run.md).
