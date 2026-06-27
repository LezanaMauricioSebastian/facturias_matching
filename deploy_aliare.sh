#!/usr/bin/env bash
set -euo pipefail

# Deploy FacturIA matching UI → Cloud Run (servicio Aliare / Odoo separado).
#
# Los valores sensibles viven en Secret Manager con sufijo _ALIARE.
# El servicio monta cada secret en el nombre de env estándar que lee la app
# (ej. secret ODOO_API_KEY_TEST_ALIARE → env ODOO_API_KEY_TEST).
#
# Requisitos: gcloud autenticado, permisos Run + Artifact Registry + Secret Manager.
#
# Uso:
#   chmod +x deploy_aliare.sh
#   ./deploy_aliare.sh --setup-secrets   # crea/actualiza secrets _ALIARE (interactivo)
#   ./deploy_aliare.sh                   # build + deploy
#   ./deploy_aliare.sh --check-secrets   # solo verifica que existan los secrets
#
# Config no sensible (hosts, URLs Odoo, DB names, user ids): copiá .env.aliare.example
# a .env.aliare y completá. Ese archivo no se sube a git.
#
# Variables opcionales de entorno:
#   PROJECT_ID          (default: fudo-481618)
#   REGION              (default: southamerica-east1)
#   SERVICE_NAME        (default: matching-ui-aliare)
#   IMAGE_NAME          (default: matching-ui-aliare)
#   REPO_NAME           (default: containers)
#   TAG                 (default: fecha-hora)
#   ENV_VARS            (override; si vacío, se arma desde .env.aliare)
#   SECRETS             (override; si vacío, se usa el mapa _ALIARE por defecto)
#   ENV_ALIARE_FILE     (default: .env.aliare)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PROJECT_ID="${PROJECT_ID:-fudo-481618}"
REGION="${REGION:-southamerica-east1}"
SERVICE_NAME="${SERVICE_NAME:-matching-ui-aliare}"
REPO_NAME="${REPO_NAME:-containers}"
IMAGE_NAME="${IMAGE_NAME:-matching-ui-aliare}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ENV_ALIARE_FILE="${ENV_ALIARE_FILE:-.env.aliare}"

# MySQL FacturIA (process / process_conversions) — defaults si no vienen del .env.
# La contraseña va solo como secret DB_PASSWORD_MYSQL_ALIARE → DB_PASSWORD_MYSQL.
ALIARE_DEFAULT_DB_HOST_MYSQL="${ALIARE_DEFAULT_DB_HOST_MYSQL:-167.250.5.17}"
ALIARE_DEFAULT_DB_PORT_MYSQL="${ALIARE_DEFAULT_DB_PORT_MYSQL:-3306}"
ALIARE_DEFAULT_DB_USER_MYSQL="${ALIARE_DEFAULT_DB_USER_MYSQL:-sudataco_gestion}"
ALIARE_DEFAULT_DB_NAME_MYSQL="${ALIARE_DEFAULT_DB_NAME_MYSQL:-sudataco_app}"

# env en runtime → secret en GCP (mismo nombre _ALIARE para Odoo Aliare)
declare -a SECRET_ENV_KEYS=(
  DB_PASSWORD
  DB_PASSWORD_MYSQL
  ODOO_PASSWORD_ALIARE
  ODOO_API_KEY_ALIARE
)

declare -a SECRET_GCP_NAMES=(
  DB_PASSWORD_ALIARE
  DB_PASSWORD_MYSQL_ALIARE
  ODOO_PASSWORD_ALIARE
  ODOO_API_KEY_ALIARE
)

MODE="deploy"
for arg in "$@"; do
  case "$arg" in
    --setup-secrets) MODE="setup-secrets" ;;
    --check-secrets) MODE="check-secrets" ;;
    -h|--help)
      sed -n '4,32p' "$0"
      exit 0
      ;;
    *)
      echo "Argumento desconocido: $arg" >&2
      echo "Uso: $0 [--setup-secrets | --check-secrets | --help]" >&2
      exit 1
      ;;
  esac
done

AR_HOST="${REGION}-docker.pkg.dev"
IMAGE_URI="${AR_HOST}/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

secret_exists() {
  local name="$1"
  gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1
}

build_default_secrets_arg() {
  local pairs=()
  local i env_key gcp_name
  for i in "${!SECRET_ENV_KEYS[@]}"; do
    env_key="${SECRET_ENV_KEYS[$i]}"
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    if secret_exists "${gcp_name}"; then
      pairs+=("${env_key}=${gcp_name}:latest")
    fi
  done
  local IFS=,
  echo "${pairs[*]}"
}

check_secrets() {
  local missing=()
  local i gcp_name
  echo "Verificando secrets _ALIARE en proyecto ${PROJECT_ID}..."
  for i in "${!SECRET_GCP_NAMES[@]}"; do
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    if secret_exists "${gcp_name}"; then
      echo "  OK  ${gcp_name}"
    else
      echo "  --  ${gcp_name} (no existe; opcional si no usás esa credencial)"
      missing+=("${gcp_name}")
    fi
  done

  local required=(DB_PASSWORD_ALIARE DB_PASSWORD_MYSQL_ALIARE)
  local req
  for req in "${required[@]}"; do
    if ! secret_exists "${req}"; then
      echo "ERROR: falta secret obligatorio ${req}" >&2
      echo "  DB_PASSWORD_ALIARE = contraseña Postgres padrón (DB_PASSWORD del .env)" >&2
      echo "  DB_PASSWORD_MYSQL_ALIARE = contraseña MySQL FacturIA" >&2
      echo "Ejecutá: $0 --setup-secrets" >&2
      exit 1
    fi
  done

  local odoo_any=0
  for name in ODOO_PASSWORD_ALIARE ODOO_API_KEY_ALIARE; do
    if secret_exists "${name}"; then
      odoo_any=1
      break
    fi
  done
  if [[ "${odoo_any}" -eq 0 ]]; then
    echo "AVISO: no hay ningún secret Odoo _ALIARE; el deploy sigue pero Odoo no conectará." >&2
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
  echo "=== Alta / actualización de secrets _ALIARE (proyecto ${PROJECT_ID}) ==="
  echo "DB_PASSWORD_ALIARE     → Postgres padrón (mismo valor que DB_PASSWORD en .env)"
  echo "DB_PASSWORD_MYSQL_ALIARE → MySQL FacturIA (process / process_conversions)"
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
    DB_PASSWORD|DB_PASSWORD_MYSQL|DB_PASSWORD_ALIARE|DB_PASSWORD_MYSQL_ALIARE|\
ODOO_PASSWORD_ALIARE|ODOO_API_KEY_ALIARE)
      return 0
      ;;
  esac
  return 1
}

is_aliare_public_env_key() {
  local key="$1"
  [[ "${key}" == *_ALIARE ]] || [[ "${key}" == "FACTURIA_ODOO_PROFILE" ]]
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

# Postgres padrón (mismo servidor que prod/Dinner si comparten histórico).
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
  is_aliare_public_env_key "${key}" \
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
  # Último valor gana por clave (para defaults < archivo < ENV_VARS explícito).
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
    "DB_HOST_MYSQL=${ALIARE_DEFAULT_DB_HOST_MYSQL}" \
    "DB_PORT_MYSQL=${ALIARE_DEFAULT_DB_PORT_MYSQL}" \
    "DB_USER_MYSQL=${ALIARE_DEFAULT_DB_USER_MYSQL}" \
    "DB_NAME_MYSQL=${ALIARE_DEFAULT_DB_NAME_MYSQL}"
}

default_aliare_env_pairs() {
  merge_env_pairs \
    "FACTURIA_ODOO_PROFILE=aliare" \
    "$(default_mysql_env_pairs)"
}

load_env_vars_from_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo ""
    return
  fi
  local pairs=()
  local line key val
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
  if [[ -f "${ENV_ALIARE_FILE}" ]]; then
    echo "${ENV_ALIARE_FILE}"
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

  IFS=',' read -r -a all_pairs <<< "$(default_aliare_env_pairs)"

  if [[ -n "${file}" ]]; then
    loaded="$(load_env_pairs_from_file "${file}")"
    if [[ -n "${loaded}" ]]; then
      local -a from_file=()
      IFS=',' read -r -a from_file <<< "${loaded}"
      all_pairs+=("${from_file[@]}")
    fi
  fi

  # Padrón Postgres: siempre desde .env local si existe (aunque el perfil venga de .env.aliare).
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
  check_secrets

  local secrets_arg="${SECRETS:-$(build_default_secrets_arg)}"
  local env_arg="${ENV_VARS:-$(build_deploy_env_vars)}"
  local env_source
  env_source="$(resolve_env_file)"

  echo "Proyecto:  ${PROJECT_ID}"
  echo "Región:    ${REGION}"
  echo "Servicio:  ${SERVICE_NAME}"
  echo "Imagen:    ${IMAGE_URI}"
  if [[ -n "${env_arg}" ]]; then
    echo "Env vars:  ${env_arg}"
    echo "             (defaults MySQL + FACTURIA_ODOO_PROFILE; override vía ${env_source:-.env.aliare})"
  else
    echo "AVISO: sin ENV_VARS; copiá .env.aliare.example → .env.aliare" >&2
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
