# Health checks Odoo

Endpoints de diagnóstico de conexión. Handlers: `api/route_odoo.py` (facade `api/routes.py`).

Índice general de la API: [api.md](api.md).

**Privacidad:** las respuestas **no** incluyen `uid` / `auth_uid` / `uid_source` de Odoo (identidad interna de la sesión XML-RPC). Internamente el servidor sí autentica; al cliente solo se expone `ok` + metadatos no sensibles (`db`, `base_url`, `company_id`, `version`, etc.).

Parámetros comunes de perfil (`empresa`, `odoo_profile_test`, `perfil`, `odoo_cloud`): ver [api.md](api.md#parámetros-comunes).

---

## `GET /api/odoo/health`

Conexión al tenant del perfil activo. Con `?empresa=N` prefiere `company_erp_credentials`; si no hay fila, usa `.env`.

**Respuesta OK** (campos típicos):
```json
{
  "ok": true,
  "db": "…",
  "base_url": "https://…",
  "jsonrpc_url": "https://…/jsonrpc",
  "odoo_profile": "default",
  "credential_source": "mysql|env",
  "version": { "server_version": "…" }
}
```

---

## `GET /api/odoo/health/import`

Conexión al tenant de **import** (misma resolución que health: MySQL por empresa → `.env`). Misma política: sin `uid` en la respuesta.

---

## `GET /api/odoo/health/credenciales_db`

Solo tablas MySQL (`company_erp_credentials` + configs). **No usa `.env`.** Sirve para validar lo **ya guardado**. El `ODOO_DB` de la tabla se pasa a `resolve_odoo_db_name` (si existe en el host se usa; si está stale se deduce por list/auth/hostname).

**Query**: `empresa` opcional (si se omite, prueba todas las activas del `PROCESS_SCHEMA`).

**Respuesta OK** (una empresa):
```json
{
  "ok": true,
  "company_id": 1,
  "company_name": "Dinner"
}
```

**Respuesta error** (mínima):
```json
{
  "ok": false,
  "error": "Dinner: No se pudo obtener uid (authenticate falló y no hay uid fijo)."
}
```

El mensaje de error puede mencionar `uid` (fallo de authenticate); eso no implica que se devuelva el número de usuario.

---

## `POST /api/odoo/health/credenciales`

Valida credenciales del **body** (antes de escribir en MySQL). **No lee** `company_erp_credentials` ni `.env`.

**Body** (keys planas o anidadas en `config`; mismas `ODOO_*` que la tabla):
```json
{
  "ODOO_BASE_URL": "https://testct.aliare.com.ar",
  "ODOO_DB": "staging-ejtngefwqs.cloudpepper.site",
  "ODOO_USER_ID": "conexion@sudata.com.ar",
  "ODOO_PASSWORD": "...",
  "ODOO_ENDPOINT": "/jsonrpc",
  "company_id": 4
}
```

**Respuesta OK**:
```json
{
  "ok": true,
  "company_id": 4,
  "db": "staging-ejtngefwqs.cloudpepper.site"
}
```

**Respuesta error** (mínima): `{"ok": false, "error": "..."}`.

Tests: `tests/test_company_erp_credentials.py` (`TestHealthCredenciales*`).
