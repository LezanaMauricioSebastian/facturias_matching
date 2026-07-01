#!/usr/bin/env bash
set -euo pipefail

# Deploy FacturIA matching UI → Cloud Run (servicio Dinner / Odoo default).
#
# Los valores sensibles viven en Secret Manager (sufijo _DINNER o nombres legacy sin sufijo).
# El servicio monta cada secret en el nombre de env estándar que lee la app
# (ej. secret ODOO_PASSWORD_DINNER → env ODOO_PASSWORD).
#
# Requisitos: gcloud autenticado, permisos Run + Artifact Registry + Secret Manager.
#
# Uso:
#   chmod +x deploy.sh
#   ./deploy.sh --dev                 # deploy rápido a odoo-dev (sin tocar env/secrets del servicio)
#   ./deploy.sh --setup-secrets       # crea/actualiza secrets _DINNER (interactivo)
#   ./deploy.sh                       # build + deploy prod (matching-ui-odoo)
#   ./deploy.sh --check-secrets       # solo verifica que existan los secrets
#
# Config no sensible (hosts, URLs Odoo, DB names, user ids): copiá .env.dinner.example
# a .env.dinner y completá. Ese archivo no se sube a git.
#
# Variables opcionales de entorno:
#   PROJECT_ID          (default: fudo-481618)
#   REGION              (default: southamerica-east1)
#   SERVICE_NAME        (default: matching-ui-odoo)
#   IMAGE_NAME          (default: matching-ui-odoo)
#   REPO_NAME           (default: containers)
#   TAG                 (default: fecha-hora)
#   ENV_VARS            (override; si vacío, se arma desde .env.dinner)
#   SECRETS             (override; si vacío, se usa el mapa _DINNER / legacy por defecto)
#   ENV_DINNER_FILE     (default: .env.dinner)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PROJECT_ID="${PROJECT_ID:-fudo-481618}"
REGION="${REGION:-southamerica-east1}"
REPO_NAME="${REPO_NAME:-containers}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ENV_DINNER_FILE="${ENV_DINNER_FILE:-.env.dinner}"
ENV_VARS="${ENV_VARS:-}"
SECRETS="${SECRETS:-}"

DEV_MODE=0
MODE="deploy"
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    --setup-secrets) MODE="setup-secrets" ;;
    --check-secrets) MODE="check-secrets" ;;
    -h|--help)
      sed -n '4,32p' "$0"
      exit 0
      ;;
    *)
      echo "Argumento desconocido: $arg" >&2
      echo "Uso: $0 [--dev | --setup-secrets | --check-secrets | --help]" >&2
      exit 1
      ;;
  esac
done

if [[ "${DEV_MODE}" -eq 1 ]]; then
  SERVICE_NAME="${SERVICE_NAME:-odoo-dev}"
  IMAGE_NAME="${IMAGE_NAME:-odoo-dev}"
  ENV_LABEL="DEV"
else
  SERVICE_NAME="${SERVICE_NAME:-matching-ui-odoo}"
  IMAGE_NAME="${IMAGE_NAME:-matching-ui-odoo}"
  ENV_LABEL="PROD"
fi

AR_HOST="${REGION}-docker.pkg.dev"
IMAGE_URI="${AR_HOST}/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

DINNER_DEFAULT_DB_HOST_MYSQL="${DINNER_DEFAULT_DB_HOST_MYSQL:-167.250.5.17}"
DINNER_DEFAULT_DB_PORT_MYSQL="${DINNER_DEFAULT_DB_PORT_MYSQL:-3306}"
DINNER_DEFAULT_DB_USER_MYSQL="${DINNER_DEFAULT_DB_USER_MYSQL:-sudataco_gestion}"
DINNER_DEFAULT_DB_NAME_MYSQL="${DINNER_DEFAULT_DB_NAME_MYSQL:-sudataco_app}"

declare -a SECRET_ENV_KEYS=(
  DB_PASSWORD
  DB_PASSWORD_MYSQL
  ODOO_PASSWORD
  ODOO_API_KEY
)

declare -a SECRET_GCP_NAMES=(
  DB_PASSWORD_DINNER
  DB_PASSWORD_MYSQL_DINNER
  ODOO_PASSWORD_DINNER
  ODOO_API_KEY_DINNER
)

secret_exists() {
  local name="$1"
  gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1
}

resolve_secret_gcp_name() {
  local env_key="$1"
  local gcp_name="$2"
  if secret_exists "${gcp_name}"; then
    echo "${gcp_name}"
    return
  fi
  if secret_exists "${env_key}"; then
    echo "${env_key}"
    return
  fi
  echo ""
}

build_default_secrets_arg() {
  local pairs=()
  local i env_key gcp_name resolved
  for i in "${!SECRET_ENV_KEYS[@]}"; do
    env_key="${SECRET_ENV_KEYS[$i]}"
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    resolved="$(resolve_secret_gcp_name "${env_key}" "${gcp_name}")"
    if [[ -n "${resolved}" ]]; then
      pairs+=("${env_key}=${resolved}:latest")
    fi
  done
  for env_key in ODOO_PASSWORD_SUDATA ODOO_API_KEY_SUDATA ODOO_PASSWORD_ALIARE ODOO_API_KEY_ALIARE; do
    resolved="$(resolve_secret_gcp_name "${env_key}" "${env_key}")"
    if [[ -n "${resolved}" ]]; then
      pairs+=("${env_key}=${resolved}:latest")
    fi
  done
  local IFS=,
  echo "${pairs[*]}"
}

check_secrets() {
  local missing=()
  local i env_key gcp_name resolved
  echo "Verificando secrets Dinner en proyecto ${PROJECT_ID}..."
  for i in "${!SECRET_GCP_NAMES[@]}"; do
    env_key="${SECRET_ENV_KEYS[$i]}"
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    resolved="$(resolve_secret_gcp_name "${env_key}" "${gcp_name}")"
    if [[ -n "${resolved}" ]]; then
      echo "  OK  ${resolved} → ${env_key}"
    else
      echo "  --  ${gcp_name} / ${env_key} (no existe; opcional si no usás esa credencial)"
      missing+=("${gcp_name}")
    fi
  done

  local pg_ok=0 mysql_ok=0
  if secret_exists "DB_PASSWORD_DINNER" || secret_exists "DB_PASSWORD"; then pg_ok=1; fi
  if secret_exists "DB_PASSWORD_MYSQL_DINNER" || secret_exists "DB_PASSWORD_MYSQL"; then mysql_ok=1; fi
  if [[ "${pg_ok}" -eq 0 ]]; then
    echo "ERROR: falta secret Postgres (DB_PASSWORD_DINNER o DB_PASSWORD)" >&2
    echo "Ejecutá: $0 --setup-secrets" >&2
    exit 1
  fi
  if [[ "${mysql_ok}" -eq 0 ]]; then
    echo "ERROR: falta secret MySQL (DB_PASSWORD_MYSQL_DINNER o DB_PASSWORD_MYSQL)" >&2
    echo "Ejecutá: $0 --setup-secrets" >&2
    exit 1
  fi

  local odoo_any=0
  for name in ODOO_PASSWORD_DINNER ODOO_PASSWORD ODOO_API_KEY_DINNER ODOO_API_KEY; do
    if secret_exists "${name}"; then
      odoo_any=1
      break
    fi
  done
  if [[ "${odoo_any}" -eq 0 ]]; then
    echo "AVISO: no hay ningún secret Odoo Dinner; el deploy sigue pero Odoo no conectará." >&2
  fi

  local sudata_any=0
  for name in ODOO_PASSWORD_SUDATA ODOO_API_KEY_SUDATA PASSWORD_SUDATA API_KEY_SUDATA; do
    if secret_exists "${name}"; then
      sudata_any=1
      break
    fi
  done
  if [[ "${sudata_any}" -eq 0 ]]; then
    echo "AVISO: no hay secrets Odoo Sudata (_SUDATA); ?odoo_cloud=1 no conectará en Cloud Run." >&2
  fi

  local aliare_any=0
  for name in ODOO_PASSWORD_ALIARE ODOO_API_KEY_ALIARE; do
    if secret_exists "${name}"; then
      aliare_any=1
      break
    fi
  done
  if [[ "${aliare_any}" -eq 0 ]]; then
    echo "AVISO: no hay secrets Odoo Aliare (_ALIARE); odoo_profile=aliare no conectará en Cloud Run." >&2
  fi

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo ""
    echo "Secrets opcionales ausentes: ${missing[*]}"
  fi
}

upsert_secret() {
  local gcp_name="$1"
  local value="$2"
  if secret_exists "${gcp_name}"; then
    echo -n "${value}" | gcloud secrets versions add "${gcp_name}" \
      --project "${PROJECT_ID}" \
      --data-file=- >/dev/null
    echo "Actualizado: ${gcp_name}"
  else
    echo -n "${value}" | gcloud secrets create "${gcp_name}" \
      --project "${PROJECT_ID}" \
      --replication-policy=automatic \
      --data-file=- >/dev/null
    echo "Creado: ${gcp_name}"
  fi
}

setup_secrets_interactive() {
  echo "=== Alta / actualización de secrets Dinner (proyecto ${PROJECT_ID}) ==="
  echo "DB_PASSWORD_DINNER       → Postgres padrón"
  echo "DB_PASSWORD_MYSQL_DINNER → MySQL FacturIA (process / process_conversions)"
  echo "ODOO_PASSWORD_DINNER   → ODOO_PASSWORD"
  echo "ODOO_API_KEY_DINNER    → ODOO_API_KEY"
  echo "Enter sin valor = omitir ese secret."
  echo ""

  gcloud services enable secretmanager.googleapis.com --project "${PROJECT_ID}" >/dev/null

  local i env_key gcp_name val confirm action
  for i in "${!SECRET_GCP_NAMES[@]}"; do
    env_key="${SECRET_ENV_KEYS[$i]}"
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    if secret_exists "${gcp_name}"; then
      read -r -p "${gcp_name} → ${env_key} [existe]. s=actualizar, Enter=omitir: " action
      [[ "${action}" == "s" || "${action}" == "S" ]] || continue
    else
      read -r -p "¿Crear ${gcp_name} → ${env_key}? (s/N): " confirm
      [[ "${confirm}" == "s" || "${confirm}" == "S" ]] || continue
    fi
    read -r -s -p "  Valor para ${gcp_name}: " val
    echo ""
    if [[ -z "${val}" ]]; then
      echo "  (vacío, omitido)"
      continue
    fi
    upsert_secret "${gcp_name}" "${val}"
  done

  echo ""
  echo "Listo. Revisá con: $0 --check-secrets"
}

is_secret_env_key() {
  local key="$1"
  case "${key}" in
    DB_PASSWORD|DB_PASSWORD_MYSQL|DB_PASSWORD_DINNER|DB_PASSWORD_MYSQL_DINNER|\
ODOO_PASSWORD|ODOO_API_KEY|ODOO_PASSWORD_DINNER|ODOO_API_KEY_DINNER|\
ODOO_PASSWORD_SUDATA|ODOO_API_KEY_SUDATA|PASSWORD_SUDATA|API_KEY_SUDATA|\
ODOO_PASSWORD_ALIARE|ODOO_API_KEY_ALIARE)
      return 0
      ;;
  esac
  return 1
}

is_dinner_odoo_public_env_key() {
  local key="$1"
  case "${key}" in
    ODOO_BASE_URL|ODOO_ENDPOINT|ODOO_DB|ODOO_USER_ID|ODOO_USER|PADRON_SOURCE)
      return 0
      ;;
  esac
  return 1
}

is_sudata_odoo_public_env_key() {
  local key="$1"
  case "${key}" in
    ODOO_BASE_URL_SUDATA|ODOO_ENDPOINT_SUDATA|ODOO_DB_SUDATA|ODOO_USER_ID_SUDATA|ODOO_USER_SUDATA|URL_SUDATA|DB_SUDATA|USERNAME_SUDATA)
      return 0
      ;;
  esac
  return 1
}

is_aliare_odoo_public_env_key() {
  local key="$1"
  case "${key}" in
    ODOO_BASE_URL_ALIARE|ODOO_ENDPOINT_ALIARE|ODOO_DB_ALIARE|ODOO_USER_ID_ALIARE|ODOO_USER_ALIARE)
      return 0
      ;;
  esac
  return 1
}

is_dinner_public_env_key() {
  local key="$1"
  [[ "${key}" == "FACTURIA_ODOO_PROFILE" ]] || is_dinner_odoo_public_env_key "${key}"
}

is_mysql_public_env_key() {
  local key="$1"
  case "${key}" in
    DB_HOST_MYSQL|DB_HOST_mysql|DB_PORT_MYSQL|DB_PORT_mysql|\
DB_USER_MYSQL|DB_USER_mysql|DB_NAME_MYSQL|DB_NAME_mysql)
      return 0
      ;;
  esac
  return 1
}

is_padron_public_env_key() {
  local key="$1"
  case "${key}" in
    DB_HOST|DB_PORT|DB_USER|DB_NAME|DB_SCHEMA|\
DB_TABLE_NAME|DB_TABLE_NAME_FALLBACK|DB_TABLE_NAME_TAXES|\
PADRON_FUZZY_MIN_SCORE|PADRON_LIMIT)
      return 0
      ;;
  esac
  return 1
}

is_deploy_public_env_key() {
  local key="$1"
  is_dinner_public_env_key "${key}" \
    || is_sudata_odoo_public_env_key "${key}" \
    || is_aliare_odoo_public_env_key "${key}" \
    || is_mysql_public_env_key "${key}" \
    || is_padron_public_env_key "${key}"
}

normalize_mysql_env_key() {
  local key="$1"
  case "${key}" in
    DB_HOST_mysql) echo "DB_HOST_MYSQL" ;;
    DB_PORT_mysql) echo "DB_PORT_MYSQL" ;;
    DB_USER_mysql) echo "DB_USER_MYSQL" ;;
    DB_NAME_mysql) echo "DB_NAME_MYSQL" ;;
    *) echo "${key}" ;;
  esac
}

merge_env_pairs() {
  declare -A seen=()
  local -a ordered_keys=()
  local pair key norm
  for pair in "$@"; do
    [[ "${pair}" != *=* ]] && continue
    key="${pair%%=*}"
    norm="$(normalize_mysql_env_key "${key}")"
    if [[ -z "${seen[${norm}]+x}" ]]; then
      ordered_keys+=("${norm}")
    fi
    seen["${norm}"]="${norm}=${pair#*=}"
  done
  local IFS=,
  local out=()
  for key in "${ordered_keys[@]}"; do
    out+=("${seen[${key}]}")
  done
  echo "${out[*]}"
}

default_mysql_env_pairs() {
  merge_env_pairs \
    "DB_HOST_MYSQL=${DINNER_DEFAULT_DB_HOST_MYSQL}" \
    "DB_PORT_MYSQL=${DINNER_DEFAULT_DB_PORT_MYSQL}" \
    "DB_USER_MYSQL=${DINNER_DEFAULT_DB_USER_MYSQL}" \
    "DB_NAME_MYSQL=${DINNER_DEFAULT_DB_NAME_MYSQL}"
}

default_dinner_env_pairs() {
  merge_env_pairs \
    "FACTURIA_ODOO_PROFILE=default" \
    "$(default_mysql_env_pairs)"
}

load_env_vars_from_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo ""
    return
  fi
  local pairs=()
  local line key val norm
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "${line}" ]] && continue
    [[ "${line}" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="$(echo "${key}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    val="$(echo "${val}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    is_secret_env_key "${key}" && continue
    if [[ "${file}" == ".env" ]]; then
      if ! is_deploy_public_env_key "${key}"; then
        continue
      fi
    fi
    norm="$(normalize_mysql_env_key "${key}")"
    if [[ "${val}" =~ ^\".*\"$ ]]; then val="${val:1:${#val}-2}"; fi
    if [[ "${val}" =~ ^\'.*\'$ ]]; then val="${val:1:${#val}-2}"; fi
    pairs+=("${norm}=${val}")
  done < "${file}"
  merge_env_pairs "${pairs[@]}"
}

load_env_pairs_from_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo ""
    return
  fi
  load_env_vars_from_file "${file}"
}

load_padron_env_pairs_from_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo ""
    return
  fi
  local pairs=()
  local line key val norm
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "${line}" ]] && continue
    [[ "${line}" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="$(echo "${key}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    val="$(echo "${val}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    is_secret_env_key "${key}" && continue
    is_padron_public_env_key "${key}" || continue
    norm="$(normalize_mysql_env_key "${key}")"
    if [[ "${val}" =~ ^\".*\"$ ]]; then val="${val:1:${#val}-2}"; fi
    if [[ "${val}" =~ ^\'.*\'$ ]]; then val="${val:1:${#val}-2}"; fi
    pairs+=("${norm}=${val}")
  done < "${file}"
  merge_env_pairs "${pairs[@]}"
}

resolve_env_file() {
  if [[ -f "${ENV_DINNER_FILE}" ]]; then
    echo "${ENV_DINNER_FILE}"
    return
  fi
  if [[ -f ".env" ]]; then
    echo ".env"
    return
  fi
  echo ""
}

build_deploy_env_vars() {
  local file loaded
  local -a all_pairs=()
  file="$(resolve_env_file)"

  IFS=',' read -r -a all_pairs <<< "$(default_dinner_env_pairs)"

  if [[ -n "${file}" ]]; then
    loaded="$(load_env_pairs_from_file "${file}")"
    if [[ -n "${loaded}" ]]; then
      local -a from_file=()
      IFS=',' read -r -a from_file <<< "${loaded}"
      all_pairs+=("${from_file[@]}")
    fi
  fi

  if [[ -f ".env" ]]; then
    loaded="$(load_padron_env_pairs_from_file ".env")"
    if [[ -n "${loaded}" ]]; then
      local -a padron_pairs=()
      IFS=',' read -r -a padron_pairs <<< "${loaded}"
      all_pairs+=("${padron_pairs[@]}")
    fi
  fi

  merge_env_pairs "${all_pairs[@]}"
}

deploy_service() {
  local secrets_arg env_arg env_source

  if [[ "${DEV_MODE}" -eq 0 ]]; then
    check_secrets
    secrets_arg="${SECRETS:-$(build_default_secrets_arg)}"
    env_arg="${ENV_VARS:-$(build_deploy_env_vars)}"
    env_source="$(resolve_env_file)"
  else
    secrets_arg="${SECRETS:-}"
    env_arg="${ENV_VARS:-}"
    env_source="(config existente en Cloud Run)"
  fi

  echo "Entorno:   ${ENV_LABEL}"
  echo "Proyecto:  ${PROJECT_ID}"
  echo "Región:    ${REGION}"
  echo "Servicio:  ${SERVICE_NAME}"
  echo "Imagen:    ${IMAGE_URI}"
  if [[ "${DEV_MODE}" -eq 1 ]]; then
    echo "Modo dev:  no se sobreescriben env vars ni secrets (salvo ENV_VARS/SECRETS explícitos)."
  elif [[ -n "${env_arg}" ]]; then
    echo "Env vars:  ${env_arg}"
    echo "             (defaults MySQL + FACTURIA_ODOO_PROFILE; override vía ${env_source:-.env.dinner})"
  else
    echo "AVISO: sin ENV_VARS; copiá .env.dinner.example → .env.dinner" >&2
  fi
  if [[ -n "${secrets_arg}" ]]; then
    echo "Secrets:   ${secrets_arg}"
  fi
  echo ""

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

  local -a deploy_args=(
    run deploy "${SERVICE_NAME}"
    --project "${PROJECT_ID}"
    --region "${REGION}"
    --image "${IMAGE_URI}"
    --allow-unauthenticated
    --port 8080
  )

  if [[ -n "${env_arg}" ]]; then
    deploy_args+=(--set-env-vars "${env_arg}")
  fi
  if [[ -n "${secrets_arg}" ]]; then
    deploy_args+=(--set-secrets "${secrets_arg}")
  fi

  gcloud "${deploy_args[@]}"
  echo ""
  echo "Deploy OK: ${SERVICE_NAME}"
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --format='value(status.url)'
}

case "${MODE}" in
  setup-secrets) setup_secrets_interactive ;;
  check-secrets) check_secrets ;;
  deploy) deploy_service ;;
esac
