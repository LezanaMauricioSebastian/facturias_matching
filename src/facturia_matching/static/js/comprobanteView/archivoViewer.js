import { buildApiQuery, escapeHtml } from "../utils/index.js";

const OVERLAY_ID = "facturaArchivoOverlay";

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

function ensureOverlay() {
  let el = document.getElementById(OVERLAY_ID);
  if (el) return el;
  el = document.createElement("div");
  el.id = OVERLAY_ID;
  el.className = "facturaArchivoOverlay";
  el.hidden = true;
  el.innerHTML = `
    <div class="facturaArchivoDialog" role="dialog" aria-modal="true" aria-label="Factura original">
      <header class="facturaArchivoHeader">
        <strong class="facturaArchivoTitle">Factura original</strong>
        <button type="button" class="facturaArchivoClose" data-archivo-close aria-label="Cerrar">×</button>
      </header>
      <div class="facturaArchivoBody" data-archivo-body></div>
      <p class="facturaArchivoError" data-archivo-error hidden></p>
    </div>
  `;
  el.addEventListener("click", (ev) => {
    if (ev.target === el || ev.target.closest("[data-archivo-close]")) {
      closeArchivoViewer();
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !el.hidden) closeArchivoViewer();
  });
  document.body.appendChild(el);
  return el;
}

function revokeBlobUrl(overlay) {
  const prev = overlay?.dataset?.blobUrl;
  if (prev) {
    try {
      URL.revokeObjectURL(prev);
    } catch {
      /* ignore */
    }
    delete overlay.dataset.blobUrl;
  }
}

export function closeArchivoViewer() {
  const el = document.getElementById(OVERLAY_ID);
  if (!el) return;
  revokeBlobUrl(el);
  el.hidden = true;
  const body = el.querySelector("[data-archivo-body]");
  if (body) body.innerHTML = "";
  const err = el.querySelector("[data-archivo-error]");
  if (err) {
    err.hidden = true;
    err.textContent = "";
  }
}

export async function openArchivoViewer(state, compIdx, archivoPath) {
  const overlay = ensureOverlay();
  const body = overlay.querySelector("[data-archivo-body]");
  const err = overlay.querySelector("[data-archivo-error]");
  revokeBlobUrl(overlay);
  const url = archivoUrl(state, compIdx);
  overlay.hidden = false;
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
    overlay.dataset.blobUrl = objectUrl;
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
