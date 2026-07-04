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
#   ./deploy.sh --dev                 # deploy a odoo-dev (Dinner TEST + Aliare testct)
#   ./deploy.sh --setup-secrets       # crea/actualiza secrets _DINNER (interactivo)
#   ./deploy.sh                       # deploy prod matching-ui-odoo (Dinner prod + Central Ticket)
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

# Proyecto GCP (Secret Manager + Cloud Run). No depende de `gcloud config get-value project`.
DEFAULT_GCP_PROJECT="fudo-481618"
PROJECT_ID="${PROJECT_ID:-${DEFAULT_GCP_PROJECT}}"
export CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
REPO_NAME="${REPO_NAME:-containers}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ENV_DINNER_FILE="${ENV_DINNER_FILE:-.env.dinner}"
ENV_VARS="${ENV_VARS:-}"
SECRETS="${SECRETS:-}"

DEV_MODE=0
MODE="deploy"
SKIP_SECRETS_CHECK=0
GCLOUD_SECRET_ACCESS_ERROR=""
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    --setup-secrets) MODE="setup-secrets" ;;
    --check-secrets) MODE="check-secrets" ;;
    --skip-secrets-check) SKIP_SECRETS_CHECK=1 ;;
    -h|--help)
      sed -n '4,32p' "$0"
      exit 0
      ;;
    *)
      echo "Argumento desconocido: $arg" >&2
      echo "Uso: $0 [--dev | --setup-secrets | --check-secrets | --skip-secrets-check | --help]" >&2
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
DINNER_DEFAULT_DB_USER_MYSQL="${DINNER_DEFAULT_DB_USER_MYSQL:-sudataco_admin}"
DINNER_DEFAULT_DB_NAME_MYSQL="${DINNER_DEFAULT_DB_NAME_MYSQL:-sudataco_app}"
DINNER_DEV_DEFAULT_DB_USER_MYSQL="${DINNER_DEV_DEFAULT_DB_USER_MYSQL:-sudataco_admin}"
DINNER_DEV_PROCESS_SCHEMA="${DINNER_DEV_PROCESS_SCHEMA:-sudataco_staging}"
DINNER_PROD_PROCESS_SCHEMA="${DINNER_PROD_PROCESS_SCHEMA:-sudataco_facturia}"

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

declare -a DEV_SECRET_ENV_KEYS=(
  DB_PASSWORD
  DB_PASSWORD_MYSQL
  ODOO_PASSWORD
  ODOO_API_KEY
  ODOO_PASSWORD_ALIARE
  ODOO_API_KEY_ALIARE
)

declare -a DEV_SECRET_GCP_NAMES=(
  DB_PASSWORD_DINNER
  DB_PASSWORD_MYSQL_DINNER
  ODOO_PASSWORD_TEST
  ODOO_API_KEY_TEST
  ODOO_PASSWORD_ALIARE
  ODOO_API_KEY_ALIARE
)

secret_exists() {
  local name="$1"
  local err=""
  if gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    return 0
  fi
  err="$(gcloud secrets describe "${name}" --project "${PROJECT_ID}" 2>&1 >/dev/null || true)"
  if [[ "${err}" == *"Reauthentication"* ]] \
    || [[ "${err}" == *"PERMISSION_DENIED"* ]] \
    || [[ "${err}" == *"Permission denied"* ]] \
    || [[ "${err}" == *"does not have"* ]]; then
    GCLOUD_SECRET_ACCESS_ERROR="${err}"
  fi
  return 1
}

report_secret_access_failure() {
  if [[ -n "${GCLOUD_SECRET_ACCESS_ERROR}" ]]; then
    echo "" >&2
    echo "ERROR: gcloud no puede leer Secret Manager en proyecto ${PROJECT_ID}." >&2
    echo "  Cuenta activa: $(gcloud config get-value account 2>/dev/null || echo '?')" >&2
    echo "  Probá: gcloud auth login" >&2
    echo "  (Los secrets pueden existir en la consola; la CLI no los ve sin auth/permisos.)" >&2
    exit 1
  fi
}

report_required_secret_missing() {
  local label="$1"
  report_secret_access_failure
  echo "ERROR: falta secret ${label}" >&2
  echo "Ejecutá: $0 --setup-secrets" >&2
  exit 1
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

build_prod_secrets_arg() {
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
  for env_key in ODOO_PASSWORD_SUDATA ODOO_API_KEY_SUDATA ODOO_PASSWORD_ALIARE; do
    resolved="$(resolve_secret_gcp_name "${env_key}" "${env_key}")"
    if [[ -n "${resolved}" ]]; then
      pairs+=("${env_key}=${resolved}:latest")
    fi
  done
  # Central Ticket (Aliare prod): solo contraseña; no montar ODOO_API_KEY_ALIARE.
  local IFS=,
  echo "${pairs[*]}"
}

build_dev_secrets_arg() {
  local pairs=()
  local i env_key gcp_name resolved
  for i in "${!DEV_SECRET_ENV_KEYS[@]}"; do
    env_key="${DEV_SECRET_ENV_KEYS[$i]}"
    gcp_name="${DEV_SECRET_GCP_NAMES[$i]}"
    resolved="$(resolve_secret_gcp_name "${env_key}" "${gcp_name}")"
    if [[ -n "${resolved}" ]]; then
      pairs+=("${env_key}=${resolved}:latest")
    fi
  done
  for env_key in ODOO_PASSWORD_SUDATA ODOO_API_KEY_SUDATA; do
    resolved="$(resolve_secret_gcp_name "${env_key}" "${env_key}")"
    if [[ -n "${resolved}" ]]; then
      pairs+=("${env_key}=${resolved}:latest")
    fi
  done
  local IFS=,
  echo "${pairs[*]}"
}

build_default_secrets_arg() {
  build_prod_secrets_arg
}

check_dev_secrets() {
  local pg_ok=0 mysql_ok=0
  GCLOUD_SECRET_ACCESS_ERROR=""
  if secret_exists "DB_PASSWORD_DINNER" || secret_exists "DB_PASSWORD"; then pg_ok=1; fi
  report_secret_access_failure
  if secret_exists "DB_PASSWORD_MYSQL_DINNER" || secret_exists "DB_PASSWORD_MYSQL"; then mysql_ok=1; fi
  report_secret_access_failure
  if [[ "${pg_ok}" -eq 0 ]]; then
    report_required_secret_missing "Postgres (DB_PASSWORD_DINNER o DB_PASSWORD)"
  fi
  if [[ "${mysql_ok}" -eq 0 ]]; then
    report_required_secret_missing "MySQL (DB_PASSWORD_MYSQL_DINNER o DB_PASSWORD_MYSQL)"
  fi
  local odoo_test=0
  for name in ODOO_PASSWORD_TEST ODOO_API_KEY_TEST; do
    if secret_exists "${name}"; then
      odoo_test=1
      break
    fi
  done
  if [[ "${odoo_test}" -eq 0 ]]; then
    echo "AVISO: no hay ODOO_PASSWORD_TEST ni ODOO_API_KEY_TEST; Dinner TEST no conectará." >&2
    echo "  Creá los secrets con: $0 --setup-secrets" >&2
  fi
}

check_secrets() {
  local missing=()
  local i env_key gcp_name resolved
  GCLOUD_SECRET_ACCESS_ERROR=""
  echo "Verificando secrets Dinner en proyecto ${PROJECT_ID}..."
  echo "  Cuenta gcloud: $(gcloud config get-value account 2>/dev/null || echo '?')"
  for i in "${!SECRET_GCP_NAMES[@]}"; do
    env_key="${SECRET_ENV_KEYS[$i]}"
    gcp_name="${SECRET_GCP_NAMES[$i]}"
    resolved="$(resolve_secret_gcp_name "${env_key}" "${gcp_name}")"
    if [[ -n "${resolved}" ]]; then
      echo "  OK  ${resolved} → ${env_key}"
    else
      report_secret_access_failure
      echo "  --  ${gcp_name} / ${env_key} (no existe; opcional si no usás esa credencial)"
      missing+=("${gcp_name}")
    fi
  done

  report_secret_access_failure

  local pg_ok=0 mysql_ok=0
  if secret_exists "DB_PASSWORD_DINNER" || secret_exists "DB_PASSWORD"; then pg_ok=1; fi
  report_secret_access_failure
  if secret_exists "DB_PASSWORD_MYSQL_DINNER" || secret_exists "DB_PASSWORD_MYSQL"; then mysql_ok=1; fi
  report_secret_access_failure
  if [[ "${pg_ok}" -eq 0 ]]; then
    report_required_secret_missing "Postgres (DB_PASSWORD_DINNER o DB_PASSWORD)"
  fi
  if [[ "${mysql_ok}" -eq 0 ]]; then
    report_required_secret_missing "MySQL (DB_PASSWORD_MYSQL_DINNER o DB_PASSWORD_MYSQL)"
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
  echo "ODOO_PASSWORD_DINNER   → ODOO_PASSWORD (prod)"
  echo "ODOO_API_KEY_DINNER    → ODOO_API_KEY (prod)"
  echo "ODOO_PASSWORD_TEST     → ODOO_PASSWORD en odoo-dev (Dinner TEST)"
  echo "ODOO_API_KEY_TEST      → ODOO_API_KEY en odoo-dev (Dinner TEST)"
  echo "Enter sin valor = omitir ese secret."
  echo ""

  gcloud services enable secretmanager.googleapis.com --project "${PROJECT_ID}" >/dev/null

  local -a setup_gcp_names=("${SECRET_GCP_NAMES[@]}" ODOO_PASSWORD_TEST ODOO_API_KEY_TEST)
  local -a setup_env_keys=("${SECRET_ENV_KEYS[@]}" ODOO_PASSWORD ODOO_API_KEY)
  local i env_key gcp_name val confirm action
  for i in "${!setup_gcp_names[@]}"; do
    env_key="${setup_env_keys[$i]}"
    gcp_name="${setup_gcp_names[$i]}"
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
ODOO_PASSWORD_TEST|ODOO_API_KEY_TEST|\
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
DB_USER_MYSQL|DB_USER_mysql|DB_NAME_MYSQL|DB_NAME_mysql|\
PROCESS_SCHEMA)
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

# odoo-dev: MySQL staging (sudataco_staging) con usuario admin.
default_dev_mysql_env_pairs() {
  merge_env_pairs \
    "PROCESS_SCHEMA=${DINNER_DEV_PROCESS_SCHEMA}" \
    "DB_USER_MYSQL=${DINNER_DEV_DEFAULT_DB_USER_MYSQL}"
}

# matching-ui-odoo (prod): MySQL FacturIA producción (sudataco_facturia).
default_prod_mysql_env_pairs() {
  merge_env_pairs \
    "PROCESS_SCHEMA=${DINNER_PROD_PROCESS_SCHEMA}"
}

default_dinner_env_pairs() {
  merge_env_pairs \
    "FACTURIA_ODOO_PROFILE=default" \
    "$(default_mysql_env_pairs)"
}

# matching-ui-odoo (prod): Dinner producción (lectura-escritura).
default_prod_dinner_env_pairs() {
  merge_env_pairs \
    "ODOO_BASE_URL=https://dinner.odoo.com" \
    "ODOO_ENDPOINT=/jsonrpc" \
    "ODOO_DB=somoswilox-dinner-main-20779820" \
    "ODOO_USER_ID=29"
}

# odoo-dev: Dinner TEST (lectura-escritura para pruebas).
# Sin ODOO_DB: la app resuelve la base vía /web/database/list + credenciales.
default_dev_dinner_env_pairs() {
  merge_env_pairs \
    "ODOO_BASE_URL=https://dinner-test.odoo.com" \
    "ODOO_ENDPOINT=/jsonrpc" \
    "ODOO_USER_ID=55" \
    "ODOO_USER=fundacion.sud@gmail.com"
}

# matching-ui-odoo (prod): perfil Aliare → Odoo Central Ticket (password, sin API key).
default_prod_aliare_env_pairs() {
  merge_env_pairs \
    "ODOO_BASE_URL_ALIARE=https://centralticket.aliare.com.ar" \
    "ODOO_ENDPOINT_ALIARE=/jsonrpc" \
    "ODOO_DB_ALIARE=centralticket" \
    "ODOO_USER_ALIARE=conexion@sudata.com.ar"
}

# odoo-dev: Aliare staging testct (como .env local).
default_dev_aliare_env_pairs() {
  merge_env_pairs \
    "ODOO_BASE_URL_ALIARE=https://testct.aliare.com.ar" \
    "ODOO_ENDPOINT_ALIARE=/jsonrpc" \
    "ODOO_DB_ALIARE=staging-ejtngefwqs.cloudpepper.site" \
    "ODOO_USER_ALIARE=conexion@sudata.com.ar"
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
    if [[ "${DEV_MODE}" -eq 1 && "${key}" == "ODOO_DB" ]]; then
      continue
    fi
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

  if [[ "${DEV_MODE}" -eq 1 ]]; then
    IFS=',' read -r -a dev_dinner <<< "$(default_dev_dinner_env_pairs)"
    all_pairs+=("${dev_dinner[@]}")
    IFS=',' read -r -a dev_aliare <<< "$(default_dev_aliare_env_pairs)"
    all_pairs+=("${dev_aliare[@]}")
    IFS=',' read -r -a dev_mysql <<< "$(default_dev_mysql_env_pairs)"
    all_pairs+=("${dev_mysql[@]}")
  else
    IFS=',' read -r -a prod_dinner <<< "$(default_prod_dinner_env_pairs)"
    all_pairs+=("${prod_dinner[@]}")
    IFS=',' read -r -a prod_aliare <<< "$(default_prod_aliare_env_pairs)"
    all_pairs+=("${prod_aliare[@]}")
    IFS=',' read -r -a prod_mysql <<< "$(default_prod_mysql_env_pairs)"
    all_pairs+=("${prod_mysql[@]}")
  fi

  merge_env_pairs "${all_pairs[@]}"
}

deploy_service() {
  local secrets_arg env_arg env_source

  if [[ "${DEV_MODE}" -eq 0 ]]; then
    if [[ "${SKIP_SECRETS_CHECK}" -eq 0 ]]; then
      check_secrets
    else
      echo "AVISO: --skip-secrets-check; no se verifican secrets." >&2
    fi
    secrets_arg="${SECRETS:-$(build_prod_secrets_arg)}"
    env_arg="${ENV_VARS:-$(build_deploy_env_vars)}"
    env_source="$(resolve_env_file)"
  else
    if [[ "${SKIP_SECRETS_CHECK}" -eq 0 ]]; then
      check_dev_secrets
    else
      echo "AVISO: --skip-secrets-check; no se verifican secrets." >&2
    fi
    secrets_arg="${SECRETS:-$(build_dev_secrets_arg)}"
    env_arg="${ENV_VARS:-$(build_deploy_env_vars)}"
    env_source="defaults odoo-dev (Dinner TEST + Aliare testct)"
  fi

  echo "Entorno:   ${ENV_LABEL}"
  echo "Proyecto:  ${PROJECT_ID}"
  echo "Región:    ${REGION}"
  echo "Servicio:  ${SERVICE_NAME}"
  echo "Imagen:    ${IMAGE_URI}"
  if [[ "${DEV_MODE}" -eq 1 ]]; then
    echo "Modo dev:  odoo-dev → Dinner TEST + Aliare testct + MySQL ${DINNER_DEV_PROCESS_SCHEMA}."
    if [[ -n "${env_arg}" ]]; then
      echo "Env vars:  ${env_arg}"
    fi
  elif [[ -n "${env_arg}" ]]; then
    echo "Modo prod: matching-ui-odoo → Dinner prod + Central Ticket + MySQL ${DINNER_PROD_PROCESS_SCHEMA}."
    echo "Env vars:  ${env_arg}"
    echo "             (override vía ${env_source:-.env.dinner})"
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
