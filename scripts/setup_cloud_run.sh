#!/usr/bin/env bash
# One-time Google Cloud setup for HapSearch on Cloud Run.
#
# Run it in Cloud Shell (console.cloud.google.com, the >_ button), which already
# has gcloud and your login:
#
#   git clone --branch feature-MSA https://github.com/Breeding-Insight/HapSearch.git
#   cd HapSearch && bash scripts/setup_cloud_run.sh
#
# Safe to re-run: anything that already exists is left alone. It creates the
# Artifact Registry repository, the Firestore database, two service accounts
# (one for the app, one for Cloud Build) with only the roles they need, and the
# secrets. It asks for the values it cannot generate. Afterwards, connect
# GitHub to Cloud Build and create the trigger as printed at the end; builds
# read the data repository through that connection, so no GitHub token is stored.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-west1}"
SERVICE="hapsearch"
REPOSITORY="hapsearch"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-hapsearch-db}"
RUNTIME_SA="hapsearch-cloud-run@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="hapsearch-cloud-build@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "No project selected. Run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

step() { printf '\n== %s\n' "$*"; }
exists() { "$@" > /dev/null 2>&1; }

echo "Project: ${PROJECT_ID} (${PROJECT_NUMBER}), region: ${REGION}"
read -r -p "Continue? [y/N] " answer
[[ "${answer}" =~ ^[Yy]$ ]] || exit 1

step "Enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  firestore.googleapis.com iam.googleapis.com --project "${PROJECT_ID}"

step "Artifact Registry repository '${REPOSITORY}'"
if exists gcloud artifacts repositories describe "${REPOSITORY}" --location "${REGION}" --project "${PROJECT_ID}"; then
  echo "already exists"
else
  gcloud artifacts repositories create "${REPOSITORY}" --repository-format=docker \
    --location "${REGION}" --description "HapSearch images" --project "${PROJECT_ID}"
  # Keep the last few images; each one carries a full copy of the database.
  cat > /tmp/hapsearch-cleanup.json <<'POLICY'
[{"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 5}},
 {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"olderThan": "30d"}}]
POLICY
  gcloud artifacts repositories set-cleanup-policies "${REPOSITORY}" --location "${REGION}" \
    --policy /tmp/hapsearch-cleanup.json --no-dry-run --project "${PROJECT_ID}"
fi

step "Firestore database '${FIRESTORE_DATABASE}' (user allowlist)"
if exists gcloud firestore databases describe --database "${FIRESTORE_DATABASE}" --project "${PROJECT_ID}"; then
  echo "already exists"
else
  gcloud firestore databases create --database "${FIRESTORE_DATABASE}" \
    --location "${REGION}" --type firestore-native --project "${PROJECT_ID}"
fi

step "Service accounts"
for account in hapsearch-cloud-run hapsearch-cloud-build; do
  if exists gcloud iam service-accounts describe "${account}@${PROJECT_ID}.iam.gserviceaccount.com" --project "${PROJECT_ID}"; then
    echo "${account}: already exists"
  else
    gcloud iam service-accounts create "${account}" --project "${PROJECT_ID}" \
      --display-name "HapSearch ${account#hapsearch-}"
  fi
done

grant_project_role() {
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member "serviceAccount:$1" \
    --role "$2" --condition None --quiet > /dev/null
  echo "$1 -> $2"
}
# The app only reads the allowlist.
grant_project_role "${RUNTIME_SA}" roles/datastore.viewer
# Cloud Build pushes images, deploys the service, writes build logs and gets
# short-lived read-only tokens for repositories linked to its GitHub connection.
grant_project_role "${BUILD_SA}" roles/run.admin
grant_project_role "${BUILD_SA}" roles/cloudbuild.readTokenAccessor
grant_project_role "${BUILD_SA}" roles/artifactregistry.writer
grant_project_role "${BUILD_SA}" roles/logging.logWriter
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member "serviceAccount:${BUILD_SA}" --role roles/iam.serviceAccountUser \
  --project "${PROJECT_ID}" --quiet > /dev/null
echo "${BUILD_SA} may deploy as ${RUNTIME_SA}"

step "Secrets"
secret_exists() { exists gcloud secrets describe "$1" --project "${PROJECT_ID}"; }
create_secret() {  # name, value from stdin
  gcloud secrets create "$1" --data-file=- --replication-policy automatic \
    --project "${PROJECT_ID}" > /dev/null
  echo "$1: created"
}
copy_or_prompt() {  # name, prompt, hidden(0/1), existing secrets to copy from...
  local name="$1" prompt="$2" hidden="$3"; shift 3
  if secret_exists "${name}"; then echo "${name}: already exists"; return; fi
  for source in "$@"; do
    if secret_exists "${source}"; then
      gcloud secrets versions access latest --secret "${source}" --project "${PROJECT_ID}" \
        | create_secret "${name}"
      echo "  (copied from ${source})"
      return
    fi
  done
  local value
  if [[ "${hidden}" == 1 ]]; then read -r -s -p "${prompt}: " value; echo; else read -r -p "${prompt}: " value; fi
  printf '%s' "${value}" | create_secret "${name}"
}

if secret_exists hapsearch-secret-key; then
  echo "hapsearch-secret-key: already exists"
else
  openssl rand -hex 32 | tr -d '\n' | create_secret hapsearch-secret-key
fi
# HapApp and AlloMate share one ORCID application; reuse it when present.
copy_or_prompt hapsearch-orcid-client-id "ORCID client ID" 0 \
  allomate-orcid-client-id hapapp-orcid-client-id
copy_or_prompt hapsearch-orcid-client-secret "ORCID client secret" 1 \
  allomate-orcid-client-secret hapapp-orcid-client-secret
grant_secret() {
  gcloud secrets add-iam-policy-binding "$1" --member "serviceAccount:$2" \
    --role roles/secretmanager.secretAccessor --project "${PROJECT_ID}" --quiet > /dev/null
}
for secret in hapsearch-secret-key hapsearch-orcid-client-id hapsearch-orcid-client-secret; do
  grant_secret "${secret}" "${RUNTIME_SA}"
done
echo "Secret access granted"

step "First allowlisted user (optional)"
read -r -p "ORCID iD to add as the first user (blank to skip): " orcid
if [[ -n "${orcid}" ]]; then
  read -r -p "Display name: " display_name
  display_name="${display_name//\"/}"  # keep the JSON below valid
  token="$(gcloud auth print-access-token)"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  status="$(curl -s -o /tmp/hapsearch-user.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
    "https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/${FIRESTORE_DATABASE}/documents/users?documentId=${orcid}" \
    -d "{\"fields\": {
          \"orcid_id\": {\"stringValue\": \"${orcid}\"},
          \"display_name\": {\"stringValue\": \"${display_name}\"},
          \"role\": {\"stringValue\": \"admin\"},
          \"is_active\": {\"booleanValue\": true},
          \"created_at\": {\"timestampValue\": \"${now}\"}}}")"
  case "${status}" in
    200) echo "Added users/${orcid}" ;;
    409) echo "users/${orcid} already exists" ;;
    *) echo "Could not add the user (HTTP ${status}):"; cat /tmp/hapsearch-user.json ;;
  esac
fi

SERVICE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
cat <<NEXT

Setup complete. Remaining steps (console):

1. Cloud Build -> Repositories -> 2nd gen -> Create host connection:
     Provider GitHub, region ${REGION}, name "github". Install the
     "Google Cloud Build" GitHub App on Breeding-Insight (an org owner may need
     to approve it) with access to HapSearch and alfalfa_haplotype_db.
   Then Link repositories: Breeding-Insight/HapSearch and
     Breeding-Insight/alfalfa_haplotype_db (keep the suggested names,
     e.g. Breeding-Insight-alfalfa_haplotype_db).
2. Cloud Build -> Triggers -> Create trigger (region ${REGION}):
     Event: Manual invocation
     Source: 2nd gen, repository Breeding-Insight-HapSearch, branch feature-MSA
     Configuration: Cloud Build configuration file, cloudbuild.yaml
     Service account: ${BUILD_SA}
   Then Run it. The first run creates the service at
     ${SERVICE_URL}
3. ORCID developer tools (the shared BI application): add the redirect URI
     ${SERVICE_URL}/auth/callback
4. Open ${SERVICE_URL}/health (should say ok), then sign in.
NEXT
