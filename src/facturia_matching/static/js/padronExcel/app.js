/** @module padronExcel/app — CRUD + padron sources (Sheets / Excel / CSV) + FacturIA iframe embed. */

const API = '/api/padron-excel';

function urlParams() {
  return new URLSearchParams(window.location.search);
}

function isEmbedMode() {
  const p = urlParams();
  if (p.has('embed')) {
    const v = (p.get('embed') || '1').trim().toLowerCase();
    return !['0', 'false', 'no'].includes(v);
  }
  return Boolean((p.get('proceso') || '').trim());
}

const $status = document.getElementById('statusPill');
const $btnToggle = document.getElementById('btnToggleForm');
const $formCard = document.getElementById('formCard');
const $btnExport = document.getElementById('btnExport');
const $btnSave = document.getElementById('btnSave');
const $btnCancel = document.getElementById('btnCancel');
const $btnAddLine = document.getElementById('btnAddLine');
const $lines = document.getElementById('linesContainer');
const $preview = document.getElementById('matchPreview');
const $tbody = document.getElementById('tableBody');
const $formTitle = document.getElementById('formTitle');
const $editingId = document.getElementById('editingId');
const $procesoBanner = document.getElementById('procesoBanner');
const $spreadsheetId = document.getElementById('spreadsheetId');
const $sheetGid = document.getElementById('sheetGid');
const $saHint = document.getElementById('saHint');
const $sourceStatus = document.getElementById('sourceStatus');
const $saEmailInline = document.getElementById('saEmailInline');

let _recordsById = {};
let _companyId = 0;
const _embed = isEmbedMode();

const $fMes = document.getElementById('fMes');
const $fSucursal = document.getElementById('fSucursal');
const $fProveedor = document.getElementById('fProveedor');
const $fCuit = document.getElementById('fCuit');
const $fFormaPago = document.getElementById('fFormaPago');
const $fEstado = document.getElementById('fEstado');
const $fTipo = document.getElementById('fTipo');

const $sheetUrl = document.getElementById('sheetUrl');
const $btnPreview = document.getElementById('btnPreview');
const $btnSaveConfig = document.getElementById('btnSaveConfig');
const $btnRefreshPadron = document.getElementById('btnRefreshPadron');
const $uploadKind = document.getElementById('uploadKind');
const $uploadFile = document.getElementById('uploadFile');
const $btnUpload = document.getElementById('btnUpload');
const $uploadStatus = document.getElementById('uploadStatus');
const $refreshStatus = document.getElementById('refreshStatus');
const $padronCounts = document.getElementById('padronCounts');

const mapSelects = {
  mapProvRazon: document.getElementById('mapProvRazon'),
  mapProvFantasia: document.getElementById('mapProvFantasia'),
  mapProvCuit: document.getElementById('mapProvCuit'),
  mapProdNombre: document.getElementById('mapProdNombre'),
  mapProdUm: document.getElementById('mapProdUm'),
  mapFp: document.getElementById('mapFp'),
  mapConc: document.getElementById('mapConc'),
  mapCat: document.getElementById('mapCat'),
};

let _columns = [];

if (_embed) {
  document.documentElement.classList.add('embed-mode');
  document.body.classList.add('embed-mode');
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (!(opts.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

function badge(score) {
  if (!score) return '';
  let cls = 'badge-low';
  if (score >= 90) cls = 'badge-high';
  else if (score >= 72) cls = 'badge-mid';
  return `<span class="badge ${cls}">${Math.round(score)}%</span>`;
}

function setStatus(msg, ok) {
  $status.textContent = msg;
  $status.className = 'status-pill ' + (ok ? 'status-ok' : 'status-loading');
}

function fillSelect($el, columns, selected, allowEmpty) {
  const cols = columns || [];
  const opts = allowEmpty ? [''] : [];
  const values = [...opts, ...cols];
  $el.innerHTML = values.map((c) => {
    const label = c || '(ninguna)';
    const sel = c === (selected || '') ? ' selected' : '';
    return `<option value="${c}"${sel}>${label}</option>`;
  }).join('');
}

function fillAllMaps(columns, mapping) {
  _columns = columns || _columns;
  const m = mapping || {};
  const p = m.proveedores || {};
  const pr = m.productos || {};
  const fp = m.formas_pago || {};
  const c = m.conceptos || {};
  fillSelect(mapSelects.mapProvRazon, _columns, p.razon_social, true);
  fillSelect(mapSelects.mapProvFantasia, _columns, p.nombre_fantasia, true);
  fillSelect(mapSelects.mapProvCuit, _columns, p.cuit, true);
  fillSelect(mapSelects.mapProdNombre, _columns, pr.nombre, true);
  fillSelect(mapSelects.mapProdUm, _columns, pr.unidad_medida, true);
  fillSelect(mapSelects.mapFp, _columns, fp.nombre, true);
  fillSelect(mapSelects.mapConc, _columns, c.nombre, true);
  fillSelect(mapSelects.mapCat, _columns, c.categoria, true);
}

function currentMapping() {
  return {
    proveedores: {
      razon_social: mapSelects.mapProvRazon.value,
      nombre_fantasia: mapSelects.mapProvFantasia.value,
      cuit: mapSelects.mapProvCuit.value,
    },
    productos: {
      nombre: mapSelects.mapProdNombre.value,
      unidad_medida: mapSelects.mapProdUm.value,
    },
    formas_pago: { nombre: mapSelects.mapFp.value },
    conceptos: { nombre: mapSelects.mapConc.value, categoria: mapSelects.mapCat.value },
  };
}

function addLine(desc = '', um = '') {
  const row = document.createElement('div');
  row.className = 'line-row';
  row.innerHTML = `<input type="text" class="line-input" placeholder="Descripción producto/servicio" value="${desc}">
    <input type="text" class="line-um" placeholder="UM" value="${um}">
    <button class="line-remove" title="Quitar">&times;</button>`;
  row.querySelector('.line-remove').addEventListener('click', () => {
    row.remove();
    if (!$lines.querySelector('.line-input')) addLine();
  });
  $lines.appendChild(row);
  return row.querySelector('.line-input');
}

$btnAddLine.addEventListener('click', () => addLine().focus());
$lines.querySelector('.line-remove').addEventListener('click', (e) => {
  e.target.closest('.line-row').remove();
  if (!$lines.querySelector('.line-input')) addLine();
});

function getLinePayload() {
  const lineas = [];
  const unidades_medida = [];
  for (const row of $lines.querySelectorAll('.line-row')) {
    const desc = row.querySelector('.line-input').value.trim();
    const um = row.querySelector('.line-um')?.value.trim() || '';
    if (!desc) continue;
    lineas.push(desc);
    unidades_medida.push(um);
  }
  return { lineas, unidades_medida };
}

function openForm(mode) {
  $formCard.style.display = '';
  $btnToggle.textContent = 'Cerrar';
  if (mode === 'edit') {
    $formTitle.textContent = 'Editar factura';
    $btnSave.textContent = 'Actualizar con matching';
  } else {
    $formTitle.textContent = 'Cargar factura';
    $btnSave.textContent = 'Guardar con matching';
  }
}

function closeForm() {
  $formCard.style.display = 'none';
  $btnToggle.textContent = '+ Nueva factura';
  resetForm();
}

$btnToggle.addEventListener('click', () => {
  const showing = $formCard.style.display !== 'none';
  if (showing) {
    closeForm();
  } else {
    resetForm();
    openForm('new');
    $fProveedor.focus();
  }
});
$btnCancel.addEventListener('click', () => closeForm());

function resetForm() {
  $editingId.value = '';
  $fMes.value = ''; $fSucursal.value = ''; $fProveedor.value = ''; $fCuit.value = '';
  $fFormaPago.value = ''; $fEstado.value = ''; $fTipo.value = '';
  $lines.innerHTML = '';
  addLine();
  $preview.innerHTML = '';
  $formTitle.textContent = 'Cargar factura';
  $btnSave.textContent = 'Guardar con matching';
}

function fillFormFromRecord(r) {
  $editingId.value = r.id || '';
  $fMes.value = r.mes || '';
  $fSucursal.value = r.sucursal || '';
  $fProveedor.value = r.proveedor || '';
  $fCuit.value = r.cuit || r.proveedor_cuit || '';
  $fFormaPago.value = r.forma_pago || '';
  $fEstado.value = r.estado_deuda || '';
  $fTipo.value = r.tipo_comprobante || '';
  $lines.innerHTML = '';
  const lineas = r.lineas || [];
  const ums = r.unidades_medida || [];
  if (!lineas.length) {
    addLine();
  } else {
    lineas.forEach((desc, i) => addLine(desc, ums[i] || ''));
  }
  schedulePreview();
}

let _previewTimer = null;
function schedulePreview() {
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(runPreview, 400);
}

async function runPreview() {
  const prov = $fProveedor.value.trim();
  const cuit = $fCuit.value.trim();
  const fp = $fFormaPago.value.trim();
  const { lineas, unidades_medida } = getLinePayload();
  if (!prov && !cuit && !fp && !lineas.length) { $preview.innerHTML = ''; return; }

  const chips = [];
  try {
    if (prov || cuit) {
      const r = await api('/match', {
        method: 'POST',
        body: JSON.stringify({ field: 'proveedor', queries: [prov || cuit], cuit, company_id: _companyId }),
      });
      const m = r.results[0];
      if (m?.match) {
        const extra = [m.nombre_fantasia, m.cuit].filter(Boolean).join(' · ');
        chips.push(`<div class="match-chip"><span class="label">Prov:</span><span class="value">${m.match}</span>${extra ? `<span class="cat">${extra}</span>` : ''}${badge(m.score)}</div>`);
      }
    }
    if (lineas.length) {
      const conc = await api('/match', { method: 'POST', body: JSON.stringify({ field: 'concepto', queries: lineas, company_id: _companyId }) });
      for (const m of conc.results) {
        if (m?.match) {
          const cat = m.categoria ? `<span class="cat">(${m.categoria})</span>` : '';
          chips.push(`<div class="match-chip"><span class="label">Conc:</span><span class="value">${m.match}</span>${cat}${badge(m.score)}</div>`);
        }
      }
      const prod = await api('/match', {
        method: 'POST',
        body: JSON.stringify({ field: 'producto', queries: lineas, unidades_medida, company_id: _companyId }),
      });
      for (const m of prod.results) {
        if (m?.match) {
          const um = m.unidad_medida ? `<span class="cat">${m.unidad_medida}${m.um_match === false ? ' ≠ factura' : ''}</span>` : '';
          chips.push(`<div class="match-chip"><span class="label">Prod:</span><span class="value">${m.match}</span>${um}${badge(m.score)}</div>`);
        }
      }
    }
    if (fp) {
      const r = await api('/match', { method: 'POST', body: JSON.stringify({ field: 'forma_pago', queries: [fp], company_id: _companyId }) });
      const m = r.results[0];
      if (m?.match) chips.push(`<div class="match-chip"><span class="label">F.Pago:</span><span class="value">${m.match}</span>${badge(m.score)}</div>`);
    }
  } catch (_) { /* silent */ }
  $preview.innerHTML = chips.join('');
}

$fProveedor.addEventListener('input', schedulePreview);
$fCuit.addEventListener('input', schedulePreview);
$fFormaPago.addEventListener('input', schedulePreview);
$lines.addEventListener('input', (e) => {
  if (e.target.classList.contains('line-input') || e.target.classList.contains('line-um')) schedulePreview();
});

$btnSave.addEventListener('click', async () => {
  const prov = $fProveedor.value.trim();
  const cuit = $fCuit.value.trim();
  if (!prov && !cuit) { $fProveedor.focus(); return; }
  const { lineas, unidades_medida } = getLinePayload();
  const payload = {
    mes: $fMes.value,
    sucursal: $fSucursal.value,
    proveedor: prov,
    cuit,
    lineas,
    unidades_medida,
    forma_pago: $fFormaPago.value.trim(),
    estado_deuda: $fEstado.value,
    tipo_comprobante: $fTipo.value,
    company_id: _companyId,
  };
  const editId = $editingId.value.trim();
  $btnSave.disabled = true;
  try {
    if (editId) {
      await api(`/facturas/${editId}`, { method: 'PUT', body: JSON.stringify(payload) });
    } else {
      await api('/facturas', { method: 'POST', body: JSON.stringify(payload) });
    }
    closeForm();
    loadTable();
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    $btnSave.disabled = false;
  }
});

function renderLists(data) {
  const prov = data.proveedores || [];
  const prod = data.productos || [];
  const conc = data.conceptos || [];
  const fp = data.formas_pago || [];
  const countsHtml = `
    <span>Proveedores: ${prov.length}</span>
    <span>Productos: ${prod.length}</span>
    <span>Conceptos: ${conc.length}</span>
    <span>Formas de pago: ${fp.length}</span>`;
  if ($padronCounts) $padronCounts.innerHTML = countsHtml;
  const $countsEmbed = document.getElementById('padronCountsEmbed');
  if ($countsEmbed) $countsEmbed.innerHTML = countsHtml;

  const provHtml = prov.slice(0, 80).map((p) => {
    const bits = [p.razon_social, p.nombre_fantasia, p.cuit].filter(Boolean);
    return `<div>${bits.join(' · ')}</div>`;
  }).join('') || '—';
  const prodHtml = prod.slice(0, 80).map((p) =>
    `<div>${p.nombre}${p.unidad_medida ? ` <span class="cell-cat">${p.unidad_medida}</span>` : ''}</div>`
  ).join('') || '—';
  const concHtml = conc.slice(0, 80).map((c) => `<div>${c}</div>`).join('') || '—';
  const fpHtml = fp.map((c) => `<div>${c}</div>`).join('') || '—';

  const listProv = document.getElementById('listProv');
  const listProd = document.getElementById('listProd');
  const listConc = document.getElementById('listConc');
  const listFp = document.getElementById('listFp');
  if (listProv) listProv.innerHTML = provHtml;
  if (listProd) listProd.innerHTML = prodHtml;
  if (listConc) listConc.innerHTML = concHtml;
  if (listFp) listFp.innerHTML = fpHtml;

  const listProvE = document.getElementById('listProvEmbed');
  const listProdE = document.getElementById('listProdEmbed');
  const listConcE = document.getElementById('listConcEmbed');
  const listFpE = document.getElementById('listFpEmbed');
  if (listProvE) listProvE.innerHTML = provHtml;
  if (listProdE) listProdE.innerHTML = prodHtml;
  if (listConcE) listConcE.innerHTML = concHtml;
  if (listFpE) listFpE.innerHTML = fpHtml;
}

function applySaHint(cfgOrData) {
  if (!$saHint && !$sourceStatus) return;
  const ok = cfgOrData.google_sa_configured;
  const email = cfgOrData.google_sa_email || '';
  const mode = cfgOrData.sheet_source_mode || (cfgOrData.config && cfgOrData.config.sheet_source_mode) || '';
  const counts = cfgOrData.row_count || {};
  if ($saEmailInline && email) $saEmailInline.textContent = email;

  const modeLabel = mode === 'private'
    ? 'Privado (service account)'
    : mode === 'public'
      ? 'Público (pub CSV)'
      : mode === 'private_unconfigured'
        ? 'ID privado sin SA'
        : (mode || 'sin fuente');

  if ($sourceStatus) {
    const n = counts.proveedores != null
      ? ` · prov ${counts.proveedores || 0} · conceptos ${counts.conceptos || 0} · f.pago ${counts.formas_pago || 0}`
      : '';
    $sourceStatus.innerHTML = ok
      ? `<span class="status-pill status-ok">Fuente: ${modeLabel}${n}</span>`
      : `<span class="status-pill status-loading">Fuente: ${modeLabel}${n} · SA no configurada</span>`;
  }

  if ($saHint) {
    if (ok && email) {
      $saHint.textContent = `SA activa: ${email}. Compartí el Sheet (Lector) a ese mail.`;
    } else if (ok) {
      $saHint.textContent = 'Service account configurada en el server.';
    } else {
      $saHint.textContent = 'Sin GOOGLE_SERVICE_ACCOUNT_JSON: solo pub CSV o upload.';
    }
  }
}

function syncIdsFromSheetUrl() {
  if (!$sheetUrl) return;
  const url = $sheetUrl.value.trim();
  if (!url) return;
  const m = url.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/);
  if (m && m[1] !== 'e' && $spreadsheetId && !$spreadsheetId.value.trim()) {
    $spreadsheetId.value = m[1];
  }
  const gm = url.match(/[?&#]gid=(\d+)/);
  if (gm && $sheetGid && !$sheetGid.value.trim()) {
    $sheetGid.value = gm[1];
  }
}

if ($sheetUrl) {
  $sheetUrl.addEventListener('change', syncIdsFromSheetUrl);
  $sheetUrl.addEventListener('blur', syncIdsFromSheetUrl);
}

async function loadPadron(force = false) {
  const data = await api(`/data?company_id=${_companyId}&force=${force ? '1' : '0'}`);
  const cfg = data.config || {};
  if ($sheetUrl) $sheetUrl.value = cfg.sheet_url || '';
  if ($spreadsheetId) $spreadsheetId.value = cfg.spreadsheet_id || '';
  if ($sheetGid) $sheetGid.value = cfg.sheet_gid || '';
  syncIdsFromSheetUrl();
  applySaHint(data);
  const previewTarget = ($spreadsheetId && $spreadsheetId.value.trim()) || cfg.spreadsheet_id || cfg.sheet_url;
  if (previewTarget) {
    try {
      const prev = await api('/preview', {
        method: 'POST',
        body: JSON.stringify({
          url: ($sheetUrl && $sheetUrl.value.trim()) || cfg.sheet_url || '',
          spreadsheet_id: ($spreadsheetId && $spreadsheetId.value.trim()) || cfg.spreadsheet_id || '',
          sheet_gid: ($sheetGid && $sheetGid.value.trim()) || cfg.sheet_gid || '',
        }),
      });
      fillAllMaps(prev.columns, cfg.mapping);
    } catch (_) {
      fillAllMaps(_columns, cfg.mapping);
    }
  } else {
    fillAllMaps(_columns, cfg.mapping);
  }
  renderLists(data);
  return data;
}

$btnRefreshPadron.addEventListener('click', async () => {
  $btnRefreshPadron.disabled = true;
  $refreshStatus.textContent = 'Bajando Sheet...';
  setStatus('Actualizando padrón...', false);
  try {
    await api(`/invalidate-cache?company_id=${_companyId}`, { method: 'POST' });
    const data = await loadPadron(true);
    const n = data.row_count || {};
    $refreshStatus.textContent = `Actualizado · prov ${n.proveedores || 0} · prod ${n.productos || 0} · conceptos ${n.conceptos || 0}`;
    setStatus('Padrón actualizado', true);
  } catch (e) {
    $refreshStatus.textContent = e.message;
    setStatus('Error al actualizar', false);
  } finally {
    $btnRefreshPadron.disabled = false;
  }
});

$btnPreview.addEventListener('click', async () => {
  syncIdsFromSheetUrl();
  const url = $sheetUrl.value.trim();
  const sid = ($spreadsheetId && $spreadsheetId.value.trim()) || '';
  if (!url && !sid) return;
  try {
    const prev = await api('/preview', {
      method: 'POST',
      body: JSON.stringify({
        url,
        spreadsheet_id: sid,
        sheet_gid: ($sheetGid && $sheetGid.value.trim()) || '',
      }),
    });
    fillAllMaps(prev.columns, currentMapping());
    if ($uploadStatus) $uploadStatus.textContent = `${prev.row_count} filas, ${prev.columns.length} columnas`;
    if ($refreshStatus) $refreshStatus.textContent = 'Lectura OK';
  } catch (e) {
    if ($uploadStatus) $uploadStatus.textContent = e.message;
    if ($refreshStatus) $refreshStatus.textContent = e.message;
  }
});

$btnSaveConfig.addEventListener('click', async () => {
  try {
    syncIdsFromSheetUrl();
    await api('/config', {
      method: 'PUT',
      body: JSON.stringify({
        company_id: _companyId,
        sheet_url: $sheetUrl.value.trim(),
        spreadsheet_id: ($spreadsheetId && $spreadsheetId.value.trim()) || '',
        sheet_gid: ($sheetGid && $sheetGid.value.trim()) || '',
        mapping: currentMapping(),
      }),
    });
    const data = await loadPadron(true);
    setStatus('Padrón actualizado', true);
    if ($uploadStatus) $uploadStatus.textContent = 'Config guardada';
    renderLists(data);
  } catch (e) {
    if ($uploadStatus) $uploadStatus.textContent = e.message;
  }
});

$btnUpload.addEventListener('click', async () => {
  const file = $uploadFile.files[0];
  if (!file) { $uploadStatus.textContent = 'Elegí un archivo'; return; }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('kind', $uploadKind.value);
  fd.append('company_id', String(_companyId));
  try {
    const res = await api('/upload', { method: 'POST', body: fd });
    fillAllMaps(res.columns, currentMapping());
    $uploadStatus.textContent = `Subido ${res.filename} (${res.row_count} filas). Mapeá columnas y guardá.`;
  } catch (e) {
    $uploadStatus.textContent = e.message;
  }
});

function renderMatchedTable(records) {
  _recordsById = {};
  for (const r of records) {
    const id = r.id || `tmp-${Object.keys(_recordsById).length}`;
    _recordsById[id] = { ...r, id };
  }
  const list = Object.values(_recordsById);
  if (!list.length) {
    $tbody.innerHTML = '<tr><td colspan="11" class="empty-state">Sin facturas en el proceso.</td></tr>';
    if ($btnExport) $btnExport.disabled = true;
    return;
  }
  if ($btnExport) $btnExport.disabled = false;
  $tbody.innerHTML = list.map((r) => {
    const umBit = r.unidad_medida
      ? ` <span class="cell-cat">${r.unidad_medida}${r.um_match === false ? ' ≠' : ''}</span>`
      : '';
    const actions = _embed
      ? ''
      : `<td class="row-actions">
        <button class="btn btn-secondary btn-sm btn-edit" data-id="${r.id}" title="Editar">✎</button>
        <button class="btn btn-danger btn-sm btn-delete" data-id="${r.id}" title="Eliminar">&#x2715;</button>
      </td>`;
    return `<tr data-id="${r.id}">
      <td>${r.mes || ''}</td>
      <td>${r.sucursal || ''}</td>
      <td>
        ${r.proveedor_match
          ? `<span class="cell-match">${r.proveedor_match}</span>${badge(r.proveedor_score)}<br><span style="color:var(--muted);font-size:.75rem">${r.proveedor || ''}</span>`
          : r.proveedor || ''}
      </td>
      <td>${r.proveedor_cuit || r.cuit || '—'}</td>
      <td>${r.concepto ? `<span class="cell-match">${r.concepto}</span>${badge(r.concepto_score)}` : '<span style="color:var(--muted)">—</span>'}</td>
      <td>${r.producto ? `<span class="cell-match">${r.producto}</span>${umBit}${badge(r.producto_score)}` : '<span style="color:var(--muted)">—</span>'}</td>
      <td><span class="cell-cat">${r.categoria || '—'}</span></td>
      <td>
        ${r.forma_pago_match
          ? `<span class="cell-match">${r.forma_pago_match}</span>${badge(r.forma_pago_score)}`
          : r.forma_pago || '—'}
      </td>
      <td>${r.estado_deuda || '—'}</td>
      <td>${r.tipo_comprobante || '—'}</td>
      ${actions || '<td></td>'}
    </tr>`;
  }).join('');
}

async function loadProcesoMatched() {
  const p = urlParams();
  const proceso = (p.get('proceso') || '').trim();
  const empresa = (p.get('empresa') || '').trim();
  const companyQ = (p.get('company_id') || '').trim();
  if (companyQ && /^\d+$/.test(companyQ)) _companyId = parseInt(companyQ, 10);

  const qs = new URLSearchParams({
    force_refresh: '1',
    company_id: String(_companyId),
  });
  if (empresa) qs.set('empresa', empresa);

  if ($procesoBanner) {
    $procesoBanner.textContent = `Proceso ${proceso}${empresa ? ` · empresa ${empresa}` : ''} — matching contra padrón Excel`;
  }

  const data = await api(`/proceso/${encodeURIComponent(proceso)}?${qs}`);
  if (data.company_id != null) _companyId = data.company_id;
  if (data.padron) {
    renderLists(data.padron);
    applySaHint({
      ...data,
      row_count: data.padron.row_count,
      google_sa_configured: data.google_sa_configured,
      google_sa_email: data.google_sa_email,
      sheet_source_mode: data.sheet_source_mode,
    });
  } else {
    applySaHint(data);
  }

  const facturas = data.facturas || [];
  renderMatchedTable(facturas.map((f, i) => ({ ...f, id: `proc-${i}` })));

  if (facturas.length) {
    fillFormFromRecord({ ...facturas[0], id: '' });
    openForm('new');
    $formTitle.textContent = 'Factura del proceso (IA + match)';
    if ($btnSave) $btnSave.textContent = 'Guardar en registro';
  }
  return data;
}

async function loadTable() {
  try {
    const records = await api('/facturas');
    renderMatchedTable(records);
  } catch (e) {
    $tbody.innerHTML = `<tr><td colspan="11" class="empty-state" style="color:var(--red)">Error: ${e.message}</td></tr>`;
  }
}

$tbody.addEventListener('click', async (e) => {
  const editBtn = e.target.closest('.btn-edit');
  if (editBtn) {
    const r = _recordsById[editBtn.dataset.id];
    if (!r) return;
    fillFormFromRecord(r);
    openForm('edit');
    $formCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  const btn = e.target.closest('.btn-delete');
  if (!btn) return;
  if (!confirm('Eliminar esta factura?')) return;
  try {
    await api(`/facturas/${btn.dataset.id}`, { method: 'DELETE' });
    if ($editingId.value === btn.dataset.id) closeForm();
    loadTable();
  } catch (err) {
    alert('Error: ' + err.message);
  }
});

$btnExport.addEventListener('click', () => {
  window.open(`${API}/facturas/export/csv`, '_blank');
});

async function init() {
  const p = urlParams();
  const companyQ = (p.get('company_id') || '').trim();
  if (companyQ && /^\d+$/.test(companyQ)) _companyId = parseInt(companyQ, 10);

  setStatus('Cargando padrón...', false);
  try {
    if (_embed && (p.get('proceso') || '').trim()) {
      await loadProcesoMatched();
      setStatus('Match listo', true);
    } else {
      await loadPadron();
      setStatus('Padrón listo', true);
      loadTable();
    }
  } catch (e) {
    setStatus('Error: ' + (e.message || e), false);
    if (!_embed) loadTable();
  }
}

init();
