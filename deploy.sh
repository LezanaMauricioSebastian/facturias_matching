#!/usr/bin/env bash
set -euo pipefail

#!/usr/bin/env bash
set -euo pipefail

# Deploy matching_ui (Odoo CSV UI) to Cloud Run (service).
#
# Requirements:
# - gcloud installed + authenticated
# - permissions to Artifact Registry + Cloud Run in the project
#
# Usage:
#   ./deploy_gcp_odoo.sh            # deploys to production (matching-ui-odoo)
#   ./deploy_gcp_odoo.sh --dev      # deploys to dev (odoo-dev)
#
# Optional env vars:
#   REGION=southamerica-east1
#   SERVICE_NAME=matching-ui-odoo
#   REPO_NAME=containers
#   IMAGE_NAME=matching-ui-odoo
#   TAG=YYYYMMDD-HHMMSS
#   ENV_VARS="K1=V1,K2=V2"
#   SECRETS="DB_PASSWORD=DB_PASSWORD:latest,DB_PASSWORD_MYSQL=DB_PASSWORD_MYSQL:latest"
#
# After deploy, set runtime env vars (DB credentials) in Cloud Run.

DEV_MODE=0
for arg in "$@"; do
  case "$arg" in
    --dev)
      DEV_MODE=1
      ;;
    -h|--help)
      sed -n '4,22p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--dev]" >&2
      exit 1
      ;;
  esac
done

if [[ "${DEV_MODE}" -eq 1 ]]; then
  DEFAULT_SERVICE_NAME="odoo-dev"
  DEFAULT_IMAGE_NAME="odoo-dev"
  ENV_LABEL="DEV"
else
  DEFAULT_SERVICE_NAME="matching-ui-odoo"
  DEFAULT_IMAGE_NAME="matching-ui-odoo"
  ENV_LABEL="PROD"
fi

PROJECT_ID="fudo-481618"
REGION="${REGION:-southamerica-east1}"
SERVICE_NAME="${SERVICE_NAME:-${DEFAULT_SERVICE_NAME}}"
REPO_NAME="${REPO_NAME:-containers}"
IMAGE_NAME="${IMAGE_NAME:-${DEFAULT_IMAGE_NAME}}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ENV_VARS="${ENV_VARS:-}"
SECRETS="${SECRETS:-}"

AR_HOST="${REGION}-docker.pkg.dev"
IMAGE_URI="${AR_HOST}/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "Environment:  ${ENV_LABEL}"
echo "Project:      ${PROJECT_ID}"
echo "Region:       ${REGION}"
echo "Service:      ${SERVICE_NAME}"
echo "Image:        ${IMAGE_URI}"

DEV_MODE=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    -h|--help)
      sed -n '4,16p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"

if [[ "${DEV_MODE}" -eq 1 ]]; then
  SERVICE_NAME="${SERVICE_NAME:-odoo-dev}"
  IMAGE_NAME="${IMAGE_NAME:-odoo-dev}"
else
  SERVICE_NAME="${SERVICE_NAME:-matching-ui-odoo}"
  IMAGE_NAME="${IMAGE_NAME:-matching-ui-odoo}"
fi

REPO_NAME="${REPO_NAME:-containers}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ENV_VARS="${ENV_VARS:-}"
SECRETS="${SECRETS:-}"

AR_HOST="${REGION}-docker.pkg.dev"
IMAGE_URI="${AR_HOST}/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "Project:  ${PROJECT_ID}"
echo "Service:  ${SERVICE_NAME}"
echo "Image:    ${IMAGE_URI}"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

if ! gcloud artifacts repositories describe "${REPO_NAME}" \
  --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPO_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --repository-format docker \
    --description "Container images" >/dev/null
fi

gcloud auth configure-docker "${AR_HOST}" --quiet >/dev/null

gcloud builds submit \
  --project "${PROJECT_ID}" \
  --config cloudbuild.yaml \
  --substitutions _IMAGE_URI="${IMAGE_URI}" \
  .

DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  --project "${PROJECT_ID}"
  --region "${REGION}"
  --image "${IMAGE_URI}"
  --allow-unauthenticated
  --port 8080
)

if [[ -n "${ENV_VARS}" ]]; then
  DEPLOY_ARGS+=( --set-env-vars "${ENV_VARS}" )
fi
if [[ -n "${SECRETS}" ]]; then
  DEPLOY_ARGS+=( --set-secrets "${SECRETS}" )
fi

gcloud "${DEPLOY_ARGS[@]}"
echo "Deployed: ${SERVICE_NAME}"
