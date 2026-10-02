import { buildApiQuery, escapeHtml } from "../utils/index.js";

const PANEL_ID = "facturaArchivoPanel";
const WIDTH_KEY = "facturia.archivoPanelWidth";
const DEFAULT_WIDTH_PCT = 50;
const MIN_WIDTH_PCT = 22;
const MAX_WIDTH_PCT = 78;

function archivoUrl(state, compIdx) {
  const pn = String(state.processNumber || "").trim();
  if (!pn) return "";
  return `/api/proceso/${encodeURIComponent(pn)}/archivo${buildApiQuery({
    comprobante_idx: compIdx,
    empresa: state.empresa || "",
  })}`;
}

function isImagePath(path) {
  return /\.(jpe?g|png|gif|webp)$/i.test(String(path || ""));
}

function clampWidthPct(pct) {
  const n = Number(pct);
  if (!Number.isFinite(n)) return DEFAULT_WIDTH_PCT;
  return Math.max(MIN_WIDTH_PCT, Math.min(MAX_WIDTH_PCT, n));
}

function readStoredWidthPct() {
  try {
    const raw = localStorage.getItem(WIDTH_KEY);
    if (raw == null || raw === "") return DEFAULT_WIDTH_PCT;
    return clampWidthPct(raw);
  } catch {
    return DEFAULT_WIDTH_PCT;
  }
}

function persistWidthPct(pct) {
  try {
    localStorage.setItem(WIDTH_KEY, String(clampWidthPct(pct)));
  } catch {
    /* ignore */
  }
}

function applyPanelWidth(panel, pct) {
  const widthPct = clampWidthPct(pct);
  panel.style.setProperty("--archivo-panel-width", `${widthPct}%`);
  panel.dataset.widthPct = String(widthPct);
  return widthPct;
}

function notifyLayoutChange() {
  requestAnimationFrame(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

function revokeBlobUrl(panel) {
  const prev = panel?.dataset?.blobUrl;
  if (prev) {
    try {
      URL.revokeObjectURL(prev);
    } catch {
      /* ignore */
    }
    delete panel.dataset.blobUrl;
  }
}

function wireResizer(panel) {
  const handle = panel.querySelector("[data-archivo-resizer]");
  if (!handle || handle.dataset.wired === "1") return;
  handle.dataset.wired = "1";

  handle.addEventListener("pointerdown", (ev) => {
    if (ev.button != null && ev.button !== 0) return;
    ev.preventDefault();
    const startX = ev.clientX;
    const startW = panel.getBoundingClientRect().width;
    const pointerId = ev.pointerId;
    try {
      handle.setPointerCapture(pointerId);
    } catch {
      /* ignore */
    }

    document.body.classList.add("archivo-resizing");

    const onMove = (e) => {
      const dx = startX - e.clientX; // drag left → wider panel
      const vw = window.innerWidth || 1;
      applyPanelWidth(panel, ((startW + dx) / vw) * 100);
    };

    const onUp = () => {
      document.body.classList.remove("archivo-resizing");
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      try {
        handle.releasePointerCapture(pointerId);
      } catch {
        /* ignore */
      }
      const pct = Number(panel.dataset.widthPct) || DEFAULT_WIDTH_PCT;
      persistWidthPct(pct);
      notifyLayoutChange();
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  });

  handle.addEventListener("dblclick", (ev) => {
    ev.preventDefault();
    applyPanelWidth(panel, DEFAULT_WIDTH_PCT);
    persistWidthPct(DEFAULT_WIDTH_PCT);
    notifyLayoutChange();
  });
}

function ensurePanel() {
  let el = document.getElementById(PANEL_ID);
  if (el) return el;

  // Drop legacy lightbox if a stale node somehow remains.
  document.getElementById("facturaArchivoOverlay")?.remove();

  el = document.createElement("aside");
  el.id = PANEL_ID;
  el.className = "facturaArchivoPanel";
  el.hidden = true;
  el.setAttribute("role", "complementary");
  el.setAttribute("aria-label", "Factura original");
  el.innerHTML = `
    <div class="facturaArchivoResizer" data-archivo-resizer title="Arrastrá para cambiar el ancho (doble clic = 50%)" role="separator" aria-orientation="vertical" aria-label="Cambiar ancho del panel" tabindex="0"></div>
    <header class="facturaArchivoHeader">
      <strong class="facturaArchivoTitle">Factura original</strong>
      <button type="button" class="facturaArchivoClose" data-archivo-close aria-label="Cerrar">×</button>
    </header>
    <div class="facturaArchivoBody" data-archivo-body></div>
    <p class="facturaArchivoError" data-archivo-error hidden></p>
  `;
  el.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-archivo-close]")) {
      closeArchivoViewer();
    }
  });
  document.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key !== "Escape" || el.hidden) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      closeArchivoViewer();
    },
    true
  );
  document.body.appendChild(el);
  wireResizer(el);
  applyPanelWidth(el, readStoredWidthPct());
  return el;
}

export function isArchivoViewerOpen() {
  const el = document.getElementById(PANEL_ID);
  return !!(el && !el.hidden);
}

export function closeArchivoViewer() {
  const el = document.getElementById(PANEL_ID);
  if (!el) return;
  revokeBlobUrl(el);
  el.hidden = true;
  document.body.classList.remove("archivo-split-open");
  document.documentElement.classList.remove("archivo-split-open");
  const body = el.querySelector("[data-archivo-body]");
  if (body) body.innerHTML = "";
  const err = el.querySelector("[data-archivo-error]");
  if (err) {
    err.hidden = true;
    err.textContent = "";
  }
  notifyLayoutChange();
}

export async function openArchivoViewer(state, compIdx, archivoPath) {
  const panel = ensurePanel();
  const body = panel.querySelector("[data-archivo-body]");
  const err = panel.querySelector("[data-archivo-error]");
  revokeBlobUrl(panel);
  const url = archivoUrl(state, compIdx);

  applyPanelWidth(panel, readStoredWidthPct());
  panel.hidden = false;
  document.body.classList.add("archivo-split-open");
  document.documentElement.classList.add("archivo-split-open");
  notifyLayoutChange();

  err.hidden = true;
  err.textContent = "";
  body.innerHTML = `<p class="facturaArchivoLoading">Cargando…</p>`;

  if (!url) {
    err.hidden = false;
    err.textContent = "No hay proceso cargado.";
    body.innerHTML = "";
    return;
  }

  try {
    const res = await fetch(url);
    if (!res.ok) {
      let detail = `No se pudo abrir el archivo (HTTP ${res.status}).`;
      try {
        const data = await res.json();
        if (data?.detail) detail = String(data.detail);
      } catch {
        /* ignore */
      }
      err.hidden = false;
      err.textContent = detail;
      body.innerHTML = "";
      return;
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    panel.dataset.blobUrl = objectUrl;
    const path = String(archivoPath || "");
    const asImage = isImagePath(path) || String(blob.type || "").startsWith("image/");
    if (asImage) {
      body.innerHTML = `<img class="facturaArchivoImg" src="${escapeHtml(objectUrl)}" alt="Factura original" />`;
    } else {
      body.innerHTML = `<iframe class="facturaArchivoFrame" title="Factura original" src="${escapeHtml(objectUrl)}"></iframe>`;
    }
  } catch {
    err.hidden = false;
    err.textContent = "No se pudo obtener el archivo.";
    body.innerHTML = "";
  }
}

/** HTML del botón (vacío si no hay `__fac_archivo`). */
export function renderVerFacturaButtonHtml(groupRows, compIdx) {
  const first = groupRows[0] || {};
  const path = String(first.__fac_archivo || "").trim();
  if (!path) return "";
  return `<button type="button" class="facturaArchivoBtn secondary" data-ver-factura="${escapeHtml(
    String(compIdx)
  )}" data-archivo-path="${escapeHtml(path)}" title="Ver foto/PDF original">Ver factura</button>`;
}

export function attachArchivoViewerHandlers(root, state) {
  if (!root) return;
  root.querySelectorAll("[data-ver-factura]").forEach((btn) => {
    if (btn.dataset.archivoWired === "1") return;
    btn.dataset.archivoWired = "1";
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const comp = btn.getAttribute("data-ver-factura");
      const path = btn.getAttribute("data-archivo-path") || "";
      openArchivoViewer(state, comp, path);
    });
  });
}
