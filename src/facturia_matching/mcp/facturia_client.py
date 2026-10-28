"""Cliente HTTP a FacturIA (erp-import init), reusando bases de erp_import_webhook."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

from facturia_matching.facturia.erp_import_webhook import resolve_facturia_base_url


class FacturiaApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class FacturiaApiClient:
    """
    Endpoints FacturIA ya integrados en matching-ui:

    - GET  /api/process/{id}/erp-import/init  → import_id + callback_token
    - POST /api/erp-imports/webhook           → lo dispara matching UI tras import
      (staging: facturia-staging.sudata.co / prod: facturia.sudata.co)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (base_url or resolve_facturia_base_url()).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self._auth_headers = self._build_auth_headers()

    @staticmethod
    def _build_auth_headers() -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        bearer = (os.environ.get("FACTURIA_API_TOKEN") or "").strip()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        cookie = (os.environ.get("FACTURIA_API_COOKIE") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def erp_import_init(self, process_id: str | int) -> Dict[str, Any]:
        """
        GET /api/process/{process_id}/erp-import/init

        Crea fila en process_erp_imports y debería devolver import_id + token
        (callback_token) para el deep-link / webhook.
        Requiere auth FacturIA (FACTURIA_API_TOKEN o FACTURIA_API_COOKIE).
        """
        pid = str(process_id).strip()
        if not pid:
            raise FacturiaApiError("process_id vacío")
        if "Authorization" not in self._auth_headers and "Cookie" not in self._auth_headers:
            raise FacturiaApiError(
                "Falta auth FacturIA: seteá FACTURIA_API_TOKEN (Bearer) "
                "o FACTURIA_API_COOKIE para llamar erp-import/init."
            )
        resp = self.session.get(
            self._url(f"/api/process/{pid}/erp-import/init"),
            headers=self._auth_headers,
            timeout=self.timeout,
        )
        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = resp.text
        if resp.status_code >= 400:
            raise FacturiaApiError(
                f"erp-import/init falló ({resp.status_code}): {data}",
                status_code=resp.status_code,
                body=data,
            )
        return data if isinstance(data, dict) else {"raw": data}


def extract_init_callback(payload: Any) -> tuple[Optional[int], str]:
    """Normaliza import_id + token desde respuesta de init (formas flexibles)."""
    if not isinstance(payload, dict):
        return None, ""
    # nested data / result comunes en APIs CI
    candidates = [payload]
    for key in ("data", "result", "payload", "erp_import"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)

    import_id = None
    token = ""
    for data in candidates:
        for key in ("import_id", "erp_import_id", "process_erp_import_id", "id"):
            raw = data.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                value = int(str(raw).strip())
            except ValueError:
                continue
            if value > 0:
                import_id = value
                break
        for key in ("token", "callback_token", "erp_token", "erp_import_token"):
            raw = data.get(key)
            if raw is not None and str(raw).strip():
                token = str(raw).strip()
                break
        if import_id is not None and token:
            break
    return import_id, token
