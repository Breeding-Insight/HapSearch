# Updating HapSearch data

HapSearch's database is rebuilt from scratch every time from the files in
[Breeding-Insight/alfalfa_haplotype_db](https://github.com/Breeding-Insight/alfalfa_haplotype_db).
Nobody edits the database directly. To add or change data, you change files in that
repository, then publish a new build.

## Where the inputs live

Everything HapSearch reads is listed in `data/hapSearch/manifest.toml` in the
data repository (copy [manifest.example.toml](manifest.example.toml) to start one):

```text
data/hapSearch/
  manifest.toml                  what goes into the database
  HapSearch_mapping.csv          genotyping source (DAl...) -> project
  HapSearch_owner_contacts.csv   project owners' contact details
  <probe design>.botloci         bottom-strand markers (optional)
  Sample_hapStatus/              one *_hapStatus.csv per genotyping order
  hapPA/                         *_hapPA_matrix.csv per FASTA version
```

The FASTA allele databases stay where they already live, in `data/versions/`; the
manifest points there with a path starting with `/` (the repository root).

Rules the build enforces:

- Every sample file name must contain its `DAl...` order number, and that number needs
  a row in `HapSearch_mapping.csv`. Every owner named there needs a row in
  `HapSearch_owner_contacts.csv`.
- The FASTA must be the version the presence calls were made against. If more than 2%
  of a matrix's alleles are missing from the FASTA, the build stops and says so.
- GitHub rejects files over 100 MB. Gzip large matrices (`gzip -k file.csv`, then commit
  `file.csv.gz` instead); the build reads them directly.

## Common changes

The manifest uses patterns (see [manifest.example.toml](manifest.example.toml)), so it
is written once. Every update below is just adding or replacing files.

| Update | What to do |
|---|---|
| New genotyping order | Add its `*_hapStatus.csv` to `Sample_hapStatus/`, add a row for its `DAl...` number to `HapSearch_mapping.csv`, and add the owner to `HapSearch_owner_contacts.csv` if they are new. |
| Re-called genotyping order | Replace the file in `Sample_hapStatus/`. If the new file has a different name, delete the old one, or both are imported. |
| New FASTA version | Commit the new FASTA and its matrix as `hapPA/<fasta name>_hapPA_matrix.csv`. The build uses the highest FASTA version and that version's matrix, and stops if the matrix is missing. |
| Mapping or contact changes | Edit `HapSearch_mapping.csv` or `HapSearch_owner_contacts.csv`; keep the file names. |
| New probe design | Replace the `.botloci` file. Keep only one; with two, the build stops and asks which. |
| Roll back to an older FASTA | Write that FASTA's exact file name as `fasta` in the manifest; the matrix follows it. |

The build log (and the database's `build_info` table) lists which FASTA, matrix and
other files were used, so you can always confirm what was picked.

Commit the change, then tag the commit so the build can be pinned to it, for example:

```bash
git tag hapsearch-2026-10-13
git push origin master --tags
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
3. Set `_DATA_REF` to the tag you pushed (or leave it as `master` for the latest commit),
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

- Cloud Build's GitHub connection (`github`, 2nd gen) with both
  `Breeding-Insight/HapSearch` and `Breeding-Insight/alfalfa_haplotype_db` linked.
  Builds read the data repository through it, so there is no token to renew. A new
  species repository is linked the same way, then named in the trigger's
  `_DATA_REPO` and `_DATA_REPO_LINK`.
- A Cloud Build trigger on the HapSearch app repository using `cloudbuild.yaml`, with
  **manual** invocation and the substitution `_DATA_REF`.
- The Cloud Run service, Firestore database and service identity described in
  [cloud-run.md](cloud-run.md).
