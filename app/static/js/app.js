/* =========================================================
   MT940 ↔ camt.053 Converter — Frontend Logic
   ========================================================= */

'use strict';

// ---------------------------------------------------------------------------
// Mode: 'mt-to-xml' | 'xml-to-mt'
// ---------------------------------------------------------------------------
let currentMode = 'mt-to-xml';

const MODE = {
  'mt-to-xml': {
    parseEndpoint:    '/api/parse',
    convertEndpoint:  '/api/convert',
    parseLoadingText: 'Analizando archivo MT940...',
    convertLoadingText: 'Generando camt.053 XML...',
    downloadLabel:    'Descargar camt.053 XML',
  },
  'xml-to-mt': {
    parseEndpoint:    '/api/parse-xml',
    convertEndpoint:  '/api/convert-xml',
    parseLoadingText: 'Analizando archivo camt.053 XML...',
    convertLoadingText: 'Generando MT940...',
    downloadLabel:    'Descargar MT940 .txt',
  },
};

// ---------------------------------------------------------------------------
// State (per-mode)
// ---------------------------------------------------------------------------
const state = {
  'mt-to-xml': { file: null },
  'xml-to-mt': { file: null },
};

// ---------------------------------------------------------------------------
// DOM references (shared)
// ---------------------------------------------------------------------------
const messages     = document.getElementById('messages');
const loading      = document.getElementById('loading');
const loadingText  = document.getElementById('loading-text');
const previewSec   = document.getElementById('preview-section');
const previewMeta  = document.getElementById('preview-meta');
const stmtsCont    = document.getElementById('statements-container');

// Mode tabs
const tabMtToXml  = document.getElementById('tab-mt-to-xml');
const tabXmlToMt  = document.getElementById('tab-xml-to-mt');
const panelMtToXml = document.getElementById('panel-mt-to-xml');
const panelXmlToMt = document.getElementById('panel-xml-to-mt');

// MT940 → XML panel
const dzMt        = document.getElementById('dz-mt');
const fiMt        = document.getElementById('fi-mt');
const fiMtInfo    = document.getElementById('fi-mt-info');
const fiMtName    = document.getElementById('fi-mt-name');
const fiMtSize    = document.getElementById('fi-mt-size');
const fiMtRemove  = document.getElementById('fi-mt-remove');
const btnMtParse  = document.getElementById('btn-mt-parse');
const btnMtDl     = document.getElementById('btn-mt-download');

// XML → MT940 panel
const dzXml       = document.getElementById('dz-xml');
const fiXml       = document.getElementById('fi-xml');
const fiXmlInfo   = document.getElementById('fi-xml-info');
const fiXmlName   = document.getElementById('fi-xml-name');
const fiXmlSize   = document.getElementById('fi-xml-size');
const fiXmlRemove = document.getElementById('fi-xml-remove');
const btnXmlParse = document.getElementById('btn-xml-parse');
const btnXmlDl    = document.getElementById('btn-xml-download');

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(2)} MB`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function indicatorLabel(ind) {
  switch ((ind || '').toUpperCase()) {
    case 'C':  return { label: 'Crédito',    cls: 'credit' };
    case 'D':  return { label: 'Débito',     cls: 'debit'  };
    case 'RC': return { label: 'Rev.Créd.',  cls: 'reversal' };
    case 'RD': return { label: 'Rev.Déb.',   cls: 'reversal' };
    default:   return { label: ind || '-',   cls: 'credit'  };
  }
}

// ---------------------------------------------------------------------------
// Mode switching
// ---------------------------------------------------------------------------
function switchMode(mode) {
  currentMode = mode;

  // Tabs
  tabMtToXml.classList.toggle('mode-tab--active', mode === 'mt-to-xml');
  tabMtToXml.setAttribute('aria-selected', mode === 'mt-to-xml');
  tabXmlToMt.classList.toggle('mode-tab--active', mode === 'xml-to-mt');
  tabXmlToMt.setAttribute('aria-selected', mode === 'xml-to-mt');

  // Panels
  panelMtToXml.classList.toggle('hidden', mode !== 'mt-to-xml');
  panelXmlToMt.classList.toggle('hidden', mode !== 'xml-to-mt');

  clearMessages();
  hidePreview();
}

tabMtToXml.addEventListener('click', () => switchMode('mt-to-xml'));
tabXmlToMt.addEventListener('click', () => switchMode('xml-to-mt'));

// ---------------------------------------------------------------------------
// File handling (generic)
// ---------------------------------------------------------------------------
function setFile(mode, file, nameEl, sizeEl, infoEl, parseBtn, dlBtn) {
  state[mode].file = file;
  nameEl.textContent = file.name;
  sizeEl.textContent = formatBytes(file.size);
  infoEl.classList.remove('hidden');
  parseBtn.disabled = false;
  dlBtn.classList.add('hidden');
  dlBtn.disabled = true;
  clearMessages();
  hidePreview();
}

function clearFile(mode, fileInput, nameEl, sizeEl, infoEl, parseBtn, dlBtn) {
  state[mode].file = null;
  fileInput.value = '';
  infoEl.classList.add('hidden');
  nameEl.textContent = '';
  sizeEl.textContent = '';
  parseBtn.disabled = true;
  dlBtn.classList.add('hidden');
  dlBtn.disabled = true;
  clearMessages();
  hidePreview();
}

// MT940 panel bindings
function setupDropZone(dz, fi, mode, nameEl, sizeEl, infoEl, parseBtn, dlBtn) {
  dz.addEventListener('click', () => fi.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); } });
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault();
    dz.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) setFile(mode, file, nameEl, sizeEl, infoEl, parseBtn, dlBtn);
  });
  fi.addEventListener('change', () => {
    if (fi.files[0]) setFile(mode, fi.files[0], nameEl, sizeEl, infoEl, parseBtn, dlBtn);
  });
}

setupDropZone(dzMt,  fiMt,  'mt-to-xml', fiMtName,  fiMtSize,  fiMtInfo,  btnMtParse,  btnMtDl);
setupDropZone(dzXml, fiXml, 'xml-to-mt', fiXmlName, fiXmlSize, fiXmlInfo, btnXmlParse, btnXmlDl);

fiMtRemove.addEventListener('click',  () => clearFile('mt-to-xml', fiMt,  fiMtName,  fiMtSize,  fiMtInfo,  btnMtParse,  btnMtDl));
fiXmlRemove.addEventListener('click', () => clearFile('xml-to-mt', fiXml, fiXmlName, fiXmlSize, fiXmlInfo, btnXmlParse, btnXmlDl));

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------
function clearMessages() {
  messages.innerHTML = '';
  messages.classList.add('hidden');
}

function showMessage(type, title, items) {
  const icons = { error: '✕', warning: '⚠', info: 'ℹ' };
  const div = document.createElement('div');
  div.className = `message message--${type}`;
  let html = `<span class="message__icon">${icons[type] || 'ℹ'}</span><div><strong>${escapeHtml(title)}</strong>`;
  if (items && items.length) {
    html += `<ul class="message__list">${items.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`;
  }
  html += '</div>';
  div.innerHTML = html;
  messages.appendChild(div);
  messages.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------
function showLoading(text) { loadingText.textContent = text; loading.classList.remove('hidden'); }
function hideLoading()     { loading.classList.add('hidden'); }

// ---------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------
function hidePreview() {
  previewSec.classList.add('hidden');
  stmtsCont.innerHTML = '';
}

function renderPreview(data) {
  stmtsCont.innerHTML = '';
  const count = (data.statements || []).length;
  const totalTxns = (data.statements || []).reduce((s, st) => s + (st.transactions || []).length, 0);
  previewMeta.textContent = `${count} statement${count !== 1 ? 's' : ''} · ${totalTxns} transacción${totalTxns !== 1 ? 'es' : ''}`;

  if (!count) {
    stmtsCont.innerHTML = '<p class="no-transactions">No se encontraron statements en el archivo.</p>';
  } else {
    (data.statements || []).forEach((stmt, i) => renderStatement(stmt, i + 1));
  }
  previewSec.classList.remove('hidden');
}

function renderStatement(stmt, num) {
  const block = document.createElement('div');
  block.className = 'statement-block';

  block.innerHTML = `
    <div class="statement-head">
      <div class="statement-head__title">Statement #${num} — Ref: ${escapeHtml(stmt.transaction_reference)}</div>
      <div class="statement-meta">
        <span><strong>Cuenta:</strong> ${escapeHtml(stmt.iban || stmt.account_id)}</span>
        ${stmt.bic      ? `<span><strong>BIC:</strong> ${escapeHtml(stmt.bic)}</span>` : ''}
        ${stmt.currency ? `<span><strong>Moneda:</strong> ${escapeHtml(stmt.currency)}</span>` : ''}
        ${stmt.statement_number ? `<span><strong>N° Extracto:</strong> ${escapeHtml(stmt.statement_number)}/${escapeHtml(stmt.sequence_number)}</span>` : ''}
        <span><strong>Transacciones:</strong> ${(stmt.transactions || []).length}</span>
      </div>
    </div>`;

  // Balances
  const balDefs = [
    { label: 'Saldo inicial',    bal: stmt.opening_balance   },
    { label: 'Saldo final',      bal: stmt.closing_balance   },
    { label: 'Saldo disponible', bal: stmt.available_balance },
  ].filter(b => b.bal);

  if (balDefs.length) {
    const row = document.createElement('div');
    row.className = 'balance-row';
    balDefs.forEach(({ label, bal }) => {
      const isCr = bal.indicator === 'C';
      row.innerHTML += `
        <div class="balance-pill">
          <span class="balance-pill__label">${label}:</span>
          <span class="balance-pill__amount balance-pill__amount--${isCr ? 'credit' : 'debit'}">
            ${isCr ? '+' : '-'}${parseFloat(bal.amount).toLocaleString('es-ES', { minimumFractionDigits: 2 })} ${escapeHtml(bal.currency)}
          </span>
          <span style="color:var(--color-muted);font-size:11px;margin-left:4px;">${bal.date}</span>
        </div>`;
    });
    block.appendChild(row);
  }

  // Transactions table
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';

  if (!(stmt.transactions || []).length) {
    wrap.innerHTML = '<p class="no-transactions">Sin transacciones en este statement.</p>';
  } else {
    const table = document.createElement('table');
    table.className = 'transactions-table';
    table.innerHTML = `
      <thead><tr>
        <th>#</th><th>Fecha valor</th><th>Fecha contable</th>
        <th>Tipo</th><th>Cód. SWIFT</th><th>Ref. cliente</th>
        <th>Ref. banco</th><th style="text-align:right">Importe</th><th>Narrativa</th>
      </tr></thead>`;
    const tbody = document.createElement('tbody');
    (stmt.transactions || []).forEach((txn, i) => {
      const ind = indicatorLabel(txn.indicator);
      const amtCls = ind.cls === 'credit' ? 'credit' : 'debit';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--color-muted);font-size:12px">${i + 1}</td>
        <td>${escapeHtml(txn.value_date || '-')}</td>
        <td>${escapeHtml(txn.booking_date || '-')}</td>
        <td><span class="badge-ind badge-ind--${ind.cls}">${escapeHtml(ind.label)}</span></td>
        <td class="td-ref">${escapeHtml(txn.transaction_type_id || '-')}</td>
        <td class="td-ref">${escapeHtml(txn.customer_reference || '-')}</td>
        <td class="td-ref">${escapeHtml(txn.bank_reference || '-')}</td>
        <td class="td-amount td-amount--${amtCls}">${parseFloat(txn.amount).toLocaleString('es-ES', { minimumFractionDigits: 2 })}</td>
        <td class="td-narrative">${escapeHtml(txn.narrative || '')}</td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }
  block.appendChild(wrap);
  stmtsCont.appendChild(block);
}

// ---------------------------------------------------------------------------
// API calls (generic)
// ---------------------------------------------------------------------------
async function doParseOrConvert(action, mode, parseBtn, dlBtn) {
  const file = state[mode].file;
  if (!file) return;

  const cfg = MODE[mode];
  const isParse = action === 'parse';
  const endpoint = isParse ? cfg.parseEndpoint : cfg.convertEndpoint;
  const loadMsg  = isParse ? cfg.parseLoadingText : cfg.convertLoadingText;

  clearMessages();
  if (isParse) hidePreview();
  showLoading(loadMsg);
  if (isParse) { parseBtn.disabled = true; } else { dlBtn.disabled = true; }

  const fd = new FormData();
  fd.append('file', file);

  try {
    const res = await fetch(endpoint, { method: 'POST', body: fd });

    if (isParse) {
      const data = await res.json();
      hideLoading();
      if (!res.ok) { showMessage('error', data.error || 'Error al procesar.', data.details); return; }
      if (data.errors && data.errors.length)   showMessage('error',   `${data.errors.length} error(es):`, data.errors);
      if (data.warnings && data.warnings.length) showMessage('warning', `Advertencias (${data.warnings.length}):`, data.warnings);
      if (data.statements && data.statements.length) {
        if (!data.errors || !data.errors.length)
          showMessage('info', `Archivo analizado: ${data.statements.length} statement(s) encontrado(s).`);
        renderPreview(data);
        dlBtn.classList.remove('hidden');
        dlBtn.disabled = false;
      } else {
        showMessage('error', 'No se encontraron statements válidos.');
      }
    } else {
      // Download
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: 'Error del servidor.' }));
        hideLoading();
        showMessage('error', err.error || 'Error al convertir.', err.details);
        return;
      }
      const blob = await res.blob();
      const disp = res.headers.get('Content-Disposition') || '';
      const nm = (disp.match(/filename="?([^"]+)"?/) || [])[1] || 'output.txt';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = nm;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      hideLoading();
    }
  } catch (err) {
    hideLoading();
    showMessage('error', 'Error de red o del servidor.', [err.message]);
  } finally {
    if (isParse) { parseBtn.disabled = false; } else { dlBtn.disabled = false; }
  }
}

// ---------------------------------------------------------------------------
// Button bindings
// ---------------------------------------------------------------------------
btnMtParse.addEventListener('click',  () => doParseOrConvert('parse',   'mt-to-xml', btnMtParse,  btnMtDl));
btnMtDl.addEventListener('click',     () => doParseOrConvert('convert', 'mt-to-xml', btnMtParse,  btnMtDl));
btnXmlParse.addEventListener('click', () => doParseOrConvert('parse',   'xml-to-mt', btnXmlParse, btnXmlDl));
btnXmlDl.addEventListener('click',    () => doParseOrConvert('convert', 'xml-to-mt', btnXmlParse, btnXmlDl));
