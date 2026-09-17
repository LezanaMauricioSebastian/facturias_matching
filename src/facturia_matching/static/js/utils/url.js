const URL_PARAM_ALIASES = {
  empresa: ["empresa", "nro_empresa", "nroEmpresa", "company", "cliente"],
  proceso: ["proceso", "nro_proceso", "nroProceso", "process", "process_number"],
  odoo_profile: ["odoo_profile_test", "perfil", "tenant"],
  /** FacturIA erp-import: callback tras guardar en Odoo. */
  import_id: ["import_id", "erp_import_id", "process_erp_import_id"],
  token: ["token", "callback_token", "erp_token", "erp_import_token"],
  excel_user: ["excel_user"],
};

/** Aliases de cliente demo → mismo modo Excel (?pepe=1). */
export const EXCEL_USER_ALIASES = ["pepe"];

function hasNonEmptyParam(params, names) {
  for (const name of names) {
    const v = params.get(name);
    if (v != null && String(v).trim() !== "") return true;
  }
  return false;
}

/** true si odoo_cloud=1 / true / yes (query o body). */
export function isOdooCloudFlag(raw) {
  const p = String(raw || "").trim().toLowerCase();
  return p === "1" || p === "true" || p === "yes" || p === "on";
}

/** true si excel_user / pepe / etc. es 1/true/yes/on. */
export function isExcelUserFlag(raw) {
  return isOdooCloudFlag(raw);
}

/** true si la URL pide matching con padrón Excel/Sheets. */
export function isExcelUserMode(urlParams = null) {
  try {
    const url = urlParams ? { ...getUrlParams(), ...urlParams } : getUrlParams();
    if (isExcelUserFlag(url.excel_user)) return true;
    for (const alias of EXCEL_USER_ALIASES) {
      if (isExcelUserFlag(url[alias])) return true;
    }
    const params = new URLSearchParams(window.location.search);
    if (isExcelUserFlag(params.get("excel_user"))) return true;
    for (const alias of EXCEL_USER_ALIASES) {
      if (isExcelUserFlag(params.get(alias))) return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** Query/body extras para APIs cuando hay modo Excel. */
export function apiExcelQueryParams(state, urlParams = {}) {
  if (!(state?.excelUser || isExcelUserMode(urlParams))) return {};
  const url = { ...getUrlParams(), ...(urlParams || {}) };
  const empresa = String(url.empresa || state?.empresa || "").trim();
  const out = { excel_user: "1" };
  if (empresa) out.empresa = empresa;
  return out;
}

/** Empresa activa: override → state → URL. */
export function currentEmpresa(state, urlParams = {}) {
  const url = { ...getUrlParams(), ...(urlParams || {}) };
  return String(url.empresa || state?.empresa || "").trim();
}

/** true si la UI va embebida (iframe, ?embed=1 o deep link FacturIA con proceso). */
export function isEmbedMode() {
  const params = new URLSearchParams(window.location.search);
  const hasProceso = hasNonEmptyParam(params, URL_PARAM_ALIASES.proceso);

  // FacturIA: ?cliente=1&proceso=221 (a veces con embed=0 explícito)
  if (hasProceso) return true;

  if (params.has("embed")) {
    const v = (params.get("embed") || "1").trim().toLowerCase();
    return v !== "0" && v !== "false" && v !== "no";
  }
  try {
    if (window.self !== window.top) return true;
  } catch {
    return true;
  }
  return false;
}

/** Lee params de FacturIA y Odoo (?odoo_profile_test=aliare, ?odoo_cloud=1). */
export function getUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const out = {
    empresa: "",
    proceso: "",
    odoo_profile: "",
    odoo_cloud: "",
    import_id: "",
    token: "",
    excel_user: "",
  };
  for (const alias of EXCEL_USER_ALIASES) {
    out[alias] = "";
  }
  for (const [key, aliases] of Object.entries(URL_PARAM_ALIASES)) {
    for (const alias of aliases) {
      const v = params.get(alias);
      if (v != null && String(v).trim() !== "") {
        out[key] = String(v).trim();
        break;
      }
    }
  }
  const oc = params.get("odoo_cloud");
  if (oc != null && String(oc).trim() !== "") {
    out.odoo_cloud = String(oc).trim();
  }
  for (const alias of EXCEL_USER_ALIASES) {
    const v = params.get(alias);
    if (v != null && String(v).trim() !== "") {
      out[alias] = String(v).trim();
    }
  }
  return out;
}

/** Query string para API (?empresa=1&perfil=aliare). */
export function buildApiQuery(params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && String(value).trim() !== "") {
      const apiKey = key === "odoo_profile" ? "odoo_profile_test" : key;
      qs.set(apiKey, String(value).trim());
    }
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/** Normaliza perfil Odoo desde URL o valor explícito. */
export function resolveOdooProfileParam(raw, odooCloud) {
  if (isOdooCloudFlag(odooCloud)) return "sudata";
  const p = String(raw || "").trim().toLowerCase();
  if (p === "aliare") return "aliare";
  if (p === "sudata") return "sudata";
  return "default";
}

/** true si ?debug=1 (o true/yes/on) para logs de timing en consola. */
export function isDebugMode() {
  try {
    const params = new URLSearchParams(window.location.search);
    const v = String(params.get("debug") || "").trim().toLowerCase();
    return v === "1" || v === "true" || v === "yes" || v === "on";
  } catch {
    return false;
  }
}

/** true si la URL trae perfil Odoo explícito (no inferido por empresa). */
export function hasExplicitOdooProfileInUrl() {
  const url = getUrlParams();
  return Boolean(isOdooCloudFlag(url.odoo_cloud) || url.odoo_profile);
}

/** true si el perfil Odoo fue fijado por URL (?odoo_profile_test / ?odoo_cloud). */
export function hasExplicitOdooProfileOverride(state) {
  if (state?.odooProfileLocked) return true;
  return hasExplicitOdooProfileInUrl();
}

/**
 * Sincroniza perfil Odoo en state.
 * ?odoo_profile_test=aliare (u odoo_cloud) gana sobre el mapeo ?empresa=N.
 */
export function syncOdooProfileState(state, urlParams = {}) {
  const url = { ...getUrlParams(), ...(urlParams || {}) };
  const odooProfile = String(url.odoo_profile || "").trim();
  const odooCloud = String(url.odoo_cloud || "").trim();
  const locked = Boolean(isOdooCloudFlag(odooCloud) || odooProfile);

  state.odooProfileLocked = locked;
  if (locked) {
    state.odooProfile = resolveOdooProfileParam(odooProfile, odooCloud);
    return;
  }

  const empresa = String(url.empresa || state?.empresa || "").trim();
  if (empresa) {
    const fromEmpresa = resolveOdooProfileFromEmpresa(empresa, state?.empresaOdooProfiles);
    if (fromEmpresa) {
      state.odooProfile = fromEmpresa;
      return;
    }
  }
}

/** Perfil Odoo desde ?empresa=N (mapa del bootstrap o fallback prod/staging). */
export function resolveOdooProfileFromEmpresa(empresa, profileMap = null) {
  const key = String(empresa || "").trim();
  if (!key) return null;
  const map = profileMap || {};
  const profile = map[key];
  if (profile === "aliare" || profile === "sudata" || profile === "default") {
    return profile;
  }
  return null;
}

/** Perfil Odoo activo: override explícito → empresa → state → default. */
export function activeOdooProfile(state) {
  if (hasExplicitOdooProfileOverride(state)) {
    const url = getUrlParams();
    if (isOdooCloudFlag(url.odoo_cloud)) return "sudata";
    if (url.odoo_profile) return resolveOdooProfileParam(url.odoo_profile);
    return resolveOdooProfileParam(state?.odooProfile);
  }

  const fromState = state?.odooProfile;
  if (fromState && fromState !== "default") return resolveOdooProfileParam(fromState);

  const url = getUrlParams();
  const empresa = String(state?.empresa || url.empresa || "").trim();
  const fromEmpresa = resolveOdooProfileFromEmpresa(empresa, state?.empresaOdooProfiles);
  if (fromEmpresa) return fromEmpresa;

  if (fromState) return resolveOdooProfileParam(fromState);
  return "default";
}

/** Params Odoo para query API según perfil activo. */
export function apiOdooQueryParams(state) {
  if (state?.excelUser || isExcelUserMode()) return {};
  const profile = activeOdooProfile(state);
  if (hasExplicitOdooProfileOverride(state)) {
    return { odoo_profile_test: profile };
  }
  const url = getUrlParams();
  const empresa = String(state?.empresa || url.empresa || "").trim();
  if (empresa && resolveOdooProfileFromEmpresa(empresa, state?.empresaOdooProfiles)) {
    return { odoo_profile_test: profile };
  }
  if (profile === "default") return {};
  return { odoo_profile_test: profile };
}

export function apiContextBody(state) {
  const body = {};
  const empresa = currentEmpresa(state);
  if (empresa) body.empresa = empresa;
  if (state.excelUser || isExcelUserMode()) {
    body.excel_user = "1";
    return body;
  }
  const profile = activeOdooProfile(state);
  if (hasExplicitOdooProfileOverride(state) || profile !== "default") {
    body.odoo_profile_test = profile;
  }
  const importId = String(state?.erpImportId || "").trim();
  const token = String(state?.erpImportToken || "").trim();
  if (importId) body.import_id = importId;
  if (token) body.token = token;
  return body;
}

/** Persiste import_id + token del deep-link FacturIA (erp-imports webhook). */
export function syncErpImportCallbackState(state, urlParams = {}) {
  const url = { ...getUrlParams(), ...(urlParams || {}) };
  const importId = String(url.import_id || "").trim();
  const token = String(url.token || "").trim();
  if (importId) state.erpImportId = importId;
  if (token) state.erpImportToken = token;
}
