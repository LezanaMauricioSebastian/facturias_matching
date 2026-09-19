#!/usr/bin/env bash
# Crea o actualiza DEEPSEEK_API_KEY en Secret Manager (proyecto fudo-481618).
# Solo pegás la key cuando te la pida; no queda en el historial del shell.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-fudo-481618}"
SECRET_NAME="DEEPSEEK_API_KEY"

echo "Proyecto: ${PROJECT_ID}"
echo "Secret:   ${SECRET_NAME}"
echo ""
read -r -s -p "Pegá DEEPSEEK_API_KEY y Enter: " KEY
echo ""
if [[ -z "${KEY}" ]]; then
  echo "Vacío: abortado." >&2
  exit 1
fi

gcloud services enable secretmanager.googleapis.com --project "${PROJECT_ID}" >/dev/null

if gcloud secrets describe "${SECRET_NAME}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo -n "${KEY}" | gcloud secrets versions add "${SECRET_NAME}" \
    --project "${PROJECT_ID}" \
    --data-file=- >/dev/null
  echo "Actualizado: ${SECRET_NAME}"
else
  echo -n "${KEY}" | gcloud secrets create "${SECRET_NAME}" \
    --project "${PROJECT_ID}" \
    --replication-policy=automatic \
    --data-file=- >/dev/null
  echo "Creado: ${SECRET_NAME}"
fi

echo "Listo. En deploy ya se monta como DEEPSEEK_API_KEY (deploy.sh / deploy_aliare.sh)."
echo "Recordá FACTURIA_UOM_AI_ENABLED=1 en el env del servicio."
