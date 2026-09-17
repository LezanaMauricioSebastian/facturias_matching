const VIEW_MODE_KEY = "facturia.viewMode";
const UNIFIED_ONE_LINE_KEY = "facturia.unifiedOneLine";

function loadViewMode() {
  try {
    const v = String(localStorage.getItem(VIEW_MODE_KEY) || "").trim();
    if (v === "carrusel" || v === "lista") return v;
  } catch (_) {
    /* private mode / blocked storage */
  }
  return "lista";
}

export function persistViewMode(mode) {
  const v = mode === "carrusel" ? "carrusel" : "lista";
  try {
    localStorage.setItem(VIEW_MODE_KEY, v);
  } catch (_) {
    /* ignore */
  }
  return v;
}

function loadUnifiedOneLine() {
  try {
    return String(localStorage.getItem(UNIFIED_ONE_LINE_KEY) || "").trim() === "1";
  } catch (_) {
    return false;
  }
}

export function persistUnifiedOneLine(on) {
  const v = !!on;
  try {
    localStorage.setItem(UNIFIED_ONE_LINE_KEY, v ? "1" : "0");
  } catch (_) {
    /* ignore */
  }
  return v;
}

export function createState() {
  return {
    columns: [],
    padronLoading: false,
    productosLoading: false,
    options: {
      proveedores: [],
      productos: [],
      conceptos: [],
      rubros: [],
      journals: [],
      cuentas: [],
      document_types: [],
      facturas_c_type_ids: [],
      etiquetas: [],
      iva_options: [],
      otros_impuestos_options: [],
    },
    rows: [],
    output_headers: [],
    rowTotals: [],
    domRefs: { totalCells: [], ivaInputs: [] },
    processNumber: "",
    empresa: "",
    source: "",
    autoSaveTimer: null,
    saveInFlight: false,
    dirty: false,
    skipAutoSave: false,
    saveStatus: "",
    odooProfile: "default",
    odooProfileLocked: false,
    empresaOdooProfiles: {},
    empresaOdooLabels: {},
    purchaseMatching: {},
    excelUser: false,
    excelPadron: null,
    uomOptionsByProductId: {},
    comprobanteTaxModes: {},
    /** 'lista' | 'carrusel' — preferencia en localStorage `facturia.viewMode`. */
    viewMode: loadViewMode(),
    /**
     * Lista: una sola tabla (1 thead + 1 scroller) cuando todas las facturas son 1 línea.
     * Preferencia en localStorage `facturia.unifiedOneLine`.
     */
    unifiedOneLine: loadUnifiedOneLine(),
    /** Índice del comprobante activo en modo carrusel. */
    carouselIndex: 0,
    uiEnv: "prod",
    processSchema: "",
    /** FacturIA process_erp_imports.id (deep-link). */
    erpImportId: "",
    /** FacturIA callback_token (deep-link). */
    erpImportToken: "",
  };
}
