# Updating HapSearch data

HapSearch's database is rebuilt from scratch every time from each species' data
repository, currently
[Breeding-Insight/alfalfa_haplotype_db](https://github.com/Breeding-Insight/alfalfa_haplotype_db).
Nobody edits the database directly. To add or change data, you change files in that
repository, then publish a new build.

The FASTA version defines a species' data. Which version is published is set in
[data_sources.toml](../data_sources.toml) in this repository: one `[[source]]` per
species, e.g. `version = "v055"`. That selects `data/versions/alfalfa_allele_db_v055.fa`
and the matching `hapPA/alfalfa_allele_db_v055_hapPA_matrix.csv`. A rebuild only
changes the species whose version you change, so new FASTA versions can be committed
to the data repository (v056, v057, ...) without affecting HapSearch until you pin one.

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
| New FASTA version | Commit the FASTA to `data/versions/` and its matrix as `hapPA/<fasta name>_hapPA_matrix.csv`. Nothing changes in HapSearch until you publish that version (below); the build stops if the version's matrix is missing. |
| Mapping or contact changes | Edit `HapSearch_mapping.csv` or `HapSearch_owner_contacts.csv`; keep the file names. |
| New probe design | Replace the `.botloci` file. Keep only one; with two, the build stops and asks which. |
| Roll back to an older FASTA | Set the older `version` in `data_sources.toml` and publish; its matrix follows. |

The build log (and the database's `build_info` table) lists which FASTA, matrix and
other files were used, so you can always confirm what was picked.

Sample files, mapping and contacts are not versioned per FASTA, so HapSearch uses the
latest committed ones (or those at a tag, if `ref` in `data_sources.toml` is a tag).
The allele check catches sample files that do not match the pinned FASTA.

## Publish

1. **New FASTA version only:** in this repository, set that species' `version` in
   `data_sources.toml` (e.g. `"v056"`), commit, and push to the branch the trigger
   builds (`feature-MSA`). Other species keep their pinned versions. For sample,
   mapping or contact updates at the same version, skip this step.
2. In the Google Cloud console, open **Cloud Build → Triggers** and click **Run** on
   `hapsearch-publish`.
3. Leave `_VERSIONS` and `_REFS` empty to build exactly what `data_sources.toml` pins,
   then click **Run trigger**.

To try a version without committing the pin, set `_VERSIONS` for that run only, e.g.
`alfalfa=v056` (separate several species with commas). Commit the pin once you are
happy with it, or the next normal run goes back to the pinned version. `_REFS` does
the same for the git branch, tag or commit that is fetched.

The pipeline ([cloudbuild.yaml](../cloudbuild.yaml)) fetches every source at its ref,
builds and checks the database, builds the app image and deploys it. If anything fails,
nothing is deployed and the build log shows why. A successful run takes roughly 10
minutes; the new version is live as soon as it finishes. The Cloud Run revision records
the exact data in `HAPSEARCH_DATA_VERSION` (e.g. `alfalfa=v055/master@1a2b3c4d5e6f`),
and the database's `build_info` table lists every source, its commit and the files used.

## Check a build on your computer (optional)

From the HapSearch app repository:

```bash
python scripts/build_database.py                            # the pinned versions
python scripts/build_database.py --versions alfalfa=v056    # try another version
python scripts/build_database.py --data-repo ../alfalfa_haplotype_db   # a local checkout
```

This takes about 3 minutes per species and needs read access to the data
repositories. It writes `data/hapsearch.db` only if every import and check passes, and
prints how many rows each table gained or lost compared with your previous local build.

## Roll back

Cloud Run keeps earlier revisions. In **Cloud Run → hapsearch → Revisions**, choose the
previous revision and **Manage traffic → 100%**. Fix the data, then publish again.

## One-time setup (already done once per project)

- Cloud Build's GitHub connection (`github`, 2nd gen) with `Breeding-Insight/HapSearch`
  and every data repository linked. Builds read the data repositories through it, so
  there is no token to renew.
- A Cloud Build trigger on the HapSearch app repository using `cloudbuild.yaml`, with
  **manual** invocation and the optional substitution `_REFS`.

## Adding a species

1. Give its data repository a `data/hapSearch/manifest.toml` (see
   [manifest.example.toml](manifest.example.toml)) using `{version}` in its FASTA path.
2. Link the repository to the `github` connection (Cloud Build → Repositories →
   2nd gen) and note its link name.
3. Add a `[[source]]` to `data_sources.toml` with its `name`, `repo`, `version`,
   `ref` and `link`, then publish as above. Species names and sample codes must not clash with
   another species.
- The Cloud Run service, Firestore database and service identity described in
  [cloud-run.md](cloud-run.md).
