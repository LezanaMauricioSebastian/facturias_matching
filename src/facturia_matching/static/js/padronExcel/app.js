/** @module padronExcel/app — CRUD + padron sources (Sheets / Excel / CSV). */

const API = '/api/padron-excel';

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

let _recordsById = {};

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
const $uploadKind = document.getElementById('uploadKind');
const $uploadFile = document.getElementById('uploadFile');
const $btnUpload = document.getElementById('btnUpload');
const $uploadStatus = document.getElementById('uploadStatus');
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
        body: JSON.stringify({ field: 'proveedor', queries: [prov || cuit], cuit }),
      });
      const m = r.results[0];
      if (m?.match) {
        const extra = [m.nombre_fantasia, m.cuit].filter(Boolean).join(' · ');
        chips.push(`<div class="match-chip"><span class="label">Prov:</span><span class="value">${m.match}</span>${extra ? `<span class="cat">${extra}</span>` : ''}${badge(m.score)}</div>`);
      }
    }
    if (lineas.length) {
      const conc = await api('/match', { method: 'POST', body: JSON.stringify({ field: 'concepto', queries: lineas }) });
      for (const m of conc.results) {
        if (m?.match) {
          const cat = m.categoria ? `<span class="cat">(${m.categoria})</span>` : '';
          chips.push(`<div class="match-chip"><span class="label">Conc:</span><span class="value">${m.match}</span>${cat}${badge(m.score)}</div>`);
        }
      }
      const prod = await api('/match', {
        method: 'POST',
        body: JSON.stringify({ field: 'producto', queries: lineas, unidades_medida }),
      });
      for (const m of prod.results) {
        if (m?.match) {
          const um = m.unidad_medida ? `<span class="cat">${m.unidad_medida}${m.um_match === false ? ' ≠ factura' : ''}</span>` : '';
          chips.push(`<div class="match-chip"><span class="label">Prod:</span><span class="value">${m.match}</span>${um}${badge(m.score)}</div>`);
        }
      }
    }
    if (fp) {
      const r = await api('/match', { method: 'POST', body: JSON.stringify({ field: 'forma_pago', queries: [fp] }) });
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
  $padronCounts.innerHTML = `
    <span>Proveedores: ${prov.length}</span>
    <span>Productos: ${prod.length}</span>
    <span>Conceptos: ${conc.length}</span>
    <span>Formas de pago: ${fp.length}</span>`;
  document.getElementById('listProv').innerHTML = prov.slice(0, 80).map((p) => {
    const bits = [p.razon_social, p.nombre_fantasia, p.cuit].filter(Boolean);
    return `<div>${bits.join(' · ')}</div>`;
  }).join('') || '—';
  document.getElementById('listProd').innerHTML = prod.slice(0, 80).map((p) =>
    `<div>${p.nombre}${p.unidad_medida ? ` <span class="cell-cat">${p.unidad_medida}</span>` : ''}</div>`
  ).join('') || '—';
  document.getElementById('listConc').innerHTML = conc.slice(0, 80).map((c) => `<div>${c}</div>`).join('') || '—';
  document.getElementById('listFp').innerHTML = fp.map((c) => `<div>${c}</div>`).join('') || '—';
}

async function loadPadron() {
  const data = await api('/data');
  const cfg = data.config || {};
  $sheetUrl.value = cfg.sheet_url || '';
  if (cfg.sheet_url) {
    try {
      const prev = await api('/preview', { method: 'POST', body: JSON.stringify({ url: cfg.sheet_url }) });
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

$btnPreview.addEventListener('click', async () => {
  const url = $sheetUrl.value.trim();
  if (!url) return;
  try {
    const prev = await api('/preview', { method: 'POST', body: JSON.stringify({ url }) });
    fillAllMaps(prev.columns, currentMapping());
    $uploadStatus.textContent = `${prev.row_count} filas, ${prev.columns.length} columnas`;
  } catch (e) {
    $uploadStatus.textContent = e.message;
  }
});

$btnSaveConfig.addEventListener('click', async () => {
  try {
    await api('/config', {
      method: 'PUT',
      body: JSON.stringify({
        company_id: 0,
        sheet_url: $sheetUrl.value.trim(),
        mapping: currentMapping(),
      }),
    });
    const data = await loadPadron();
    setStatus('Padrón actualizado', true);
    $uploadStatus.textContent = 'Config guardada';
    renderLists(data);
  } catch (e) {
    $uploadStatus.textContent = e.message;
  }
});

$btnUpload.addEventListener('click', async () => {
  const file = $uploadFile.files[0];
  if (!file) { $uploadStatus.textContent = 'Elegí un archivo'; return; }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('kind', $uploadKind.value);
  fd.append('company_id', '0');
  try {
    const res = await api('/upload', { method: 'POST', body: fd });
    fillAllMaps(res.columns, currentMapping());
    $uploadStatus.textContent = `Subido ${res.filename} (${res.row_count} filas). Mapeá columnas y guardá.`;
  } catch (e) {
    $uploadStatus.textContent = e.message;
  }
});

async function loadTable() {
  try {
    const records = await api('/facturas');
    _recordsById = {};
    for (const r of records) _recordsById[r.id] = r;
    if (!records.length) {
      $tbody.innerHTML = '<tr><td colspan="11" class="empty-state">No hay facturas cargadas. Usá "+ Nueva factura" para empezar.</td></tr>';
      $btnExport.disabled = true;
      return;
    }
    $btnExport.disabled = false;
    $tbody.innerHTML = records.map((r) => {
      const umBit = r.unidad_medida
        ? ` <span class="cell-cat">${r.unidad_medida}${r.um_match === false ? ' ≠' : ''}</span>`
        : '';
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
      <td class="row-actions">
        <button class="btn btn-secondary btn-sm btn-edit" data-id="${r.id}" title="Editar">✎</button>
        <button class="btn btn-danger btn-sm btn-delete" data-id="${r.id}" title="Eliminar">&#x2715;</button>
      </td>
    </tr>`;
    }).reverse().join('');
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
  setStatus('Cargando padrón...', false);
  try {
    await loadPadron();
    setStatus('Padrón listo', true);
  } catch (e) {
    setStatus('Error padrón', false);
  }
  loadTable();
}

init();
