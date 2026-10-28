"""HTTP client against the matching-ui FastAPI (and optional FacturIA base)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests


class MatchingApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MatchingApiClient:
    """Calls local/remote matching-ui REST endpoints used by MCP tools."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 120.0,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (base_url or os.environ.get("FACTURIA_MATCHING_URL") or "http://127.0.0.1:8080").rstrip(
            "/"
        )
        self.timeout = timeout
        self.session = session or requests.Session()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _params(
        self,
        *,
        empresa: Optional[str] = None,
        odoo_profile: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if empresa:
            params["empresa"] = empresa
        if odoo_profile:
            params["odoo_profile_test"] = odoo_profile
            params["perfil"] = odoo_profile
        if extra:
            params.update({k: v for k, v in extra.items() if v is not None})
        return params

    def _raise_for_status(self, resp: requests.Response, action: str) -> Any:
        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = resp.text
        if resp.status_code >= 400:
            detail = data
            if isinstance(data, dict):
                detail = data.get("detail") or data.get("message") or data
            raise MatchingApiError(
                f"{action} falló ({resp.status_code}): {detail}",
                status_code=resp.status_code,
                body=data,
            )
        return data

    def get_proceso(
        self,
        process_number: str,
        *,
        empresa: Optional[str] = None,
        odoo_profile: Optional[str] = None,
        regenerate: bool = False,
    ) -> Dict[str, Any]:
        extra = {"regenerate": "true"} if regenerate else None
        resp = self.session.get(
            self._url(f"/api/proceso/{process_number}"),
            params=self._params(empresa=empresa, odoo_profile=odoo_profile, extra=extra),
            timeout=self.timeout,
        )
        return self._raise_for_status(resp, "GET /api/proceso")

    def search_partners(
        self,
        query: str,
        *,
        limit: int = 20,
        empresa: Optional[str] = None,
        odoo_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        resp = self.session.get(
            self._url("/api/partners/search"),
            params=self._params(
                empresa=empresa,
                odoo_profile=odoo_profile,
                extra={"q": query, "limit": max(1, min(int(limit), 100))},
            ),
            timeout=self.timeout,
        )
        return self._raise_for_status(resp, "GET /api/partners/search")

    def odoo_health(
        self,
        *,
        empresa: Optional[str] = None,
        odoo_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        resp = self.session.get(
            self._url("/api/odoo/health"),
            params=self._params(empresa=empresa, odoo_profile=odoo_profile),
            timeout=min(self.timeout, 30.0),
        )
        return self._raise_for_status(resp, "GET /api/odoo/health")

    def import_odoo(
        self,
        rows: list,
        *,
        empresa: Optional[str] = None,
        odoo_profile: Optional[str] = None,
        skip_duplicates: bool = True,
        update_taxes_if_exists: bool = True,
        import_id: Optional[int] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "rows": rows,
            "skip_duplicates": skip_duplicates,
            "update_taxes_if_exists": update_taxes_if_exists,
            "target_state": "draft",
        }
        if empresa:
            body["empresa"] = empresa
        if odoo_profile:
            body["odoo_profile"] = odoo_profile
            body["odoo_profile_test"] = odoo_profile
        if import_id is not None:
            body["import_id"] = import_id
        if token:
            body["token"] = token
        resp = self.session.post(
            self._url("/api/odoo/import"),
            json=body,
            params=self._params(empresa=empresa, odoo_profile=odoo_profile),
            timeout=self.timeout,
        )
        return self._raise_for_status(resp, "POST /api/odoo/import")
