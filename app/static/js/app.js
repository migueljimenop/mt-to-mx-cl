/* =========================================================
   MT940 → camt.053 Converter — Frontend Logic
   ========================================================= */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let selectedFile = null;
let lastParseResult = null;

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------
const dropZone    = document.getElementById('drop-zone');
const fileInput   = document.getElementById('file-input');
const fileInfo    = document.getElementById('file-info');
const fileName    = document.getElementById('file-name');
const fileSize    = document.getElementById('file-size');
const fileRemove  = document.getElementById('file-remove');
const btnParse    = document.getElementById('btn-parse');
const btnDownload = document.getElementById('btn-download');
const messages    = document.getElementById('messages');
const loading     = document.getElementById('loading');
const loadingText = document.getElementById('loading-text');
const previewSec  = document.getElementById('preview-section');
const previewMeta = document.getElementById('preview-meta');
const stmtsContainer = document.getElementById('statements-container');

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatAmount(amount, indicator) {
  const num = parseFloat(amount);
  const abs = Math.abs(num).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return abs;
}

function indicatorLabel(ind) {
  switch ((ind || '').toUpperCase()) {
    case 'C':  return { label: 'Crédito', cls: 'credit' };
    case 'D':  return { label: 'Débito',  cls: 'debit' };
    case 'RC': return { label: 'Rev.Créd', cls: 'reversal' };
    case 'RD': return { label: 'Rev.Déb', cls: 'reversal' };
    case 'CN': return { label: 'Crédito', cls: 'credit' };
    case 'DN': return { label: 'Débito',  cls: 'debit' };
    default:   return { label: ind || '-', cls: 'credit' };
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// File handling
// ---------------------------------------------------------------------------
function setFile(file) {
  selectedFile = file;
  lastParseResult = null;

  fileInfo.classList.remove('hidden');
  fileName.textContent = file.name;
  fileSize.textContent = formatBytes(file.size);
  btnParse.disabled = false;
  btnDownload.classList.add('hidden');
  btnDownload.disabled = true;

  clearMessages();
  hidePreview();
}

function clearFile() {
  selectedFile = null;
  lastParseResult = null;
  fileInput.value = '';

  fileInfo.classList.add('hidden');
  btnParse.disabled = true;
  btnDownload.classList.add('hidden');
  btnDownload.disabled = true;

  clearMessages();
  hidePreview();
}

function clearMessages() {
  messages.innerHTML = '';
  messages.classList.add('hidden');
}

function hidePreview() {
  previewSec.classList.add('hidden');
  stmtsContainer.innerHTML = '';
}

function showLoading(text) {
  loadingText.textContent = text || 'Procesando...';
  loading.classList.remove('hidden');
}

function hideLoading() {
  loading.classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------
function showMessage(type, title, items) {
  const icons = {
    error:   '✕',
    warning: '⚠',
    info:    'ℹ',
  };
  const div = document.createElement('div');
  div.className = `message message--${type}`;

  let html = `<span class="message__icon">${icons[type] || 'ℹ'}</span>`;
  html += `<div><strong>${escapeHtml(title)}</strong>`;
  if (items && items.length > 0) {
    html += `<ul class="message__list">`;
    items.forEach(item => { html += `<li>${escapeHtml(item)}</li>`; });
    html += `</ul>`;
  }
  html += `</div>`;
  div.innerHTML = html;

  messages.appendChild(div);
  messages.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Preview rendering
// ---------------------------------------------------------------------------
function renderPreview(data) {
  stmtsContainer.innerHTML = '';

  const count = data.statements ? data.statements.length : 0;
  const totalTxns = (data.statements || []).reduce((s, st) => s + (st.transactions || []).length, 0);
  previewMeta.textContent = `${count} statement${count !== 1 ? 's' : ''} · ${totalTxns} transacción${totalTxns !== 1 ? 'es' : ''}`;

  if (!count) {
    stmtsContainer.innerHTML = '<p class="no-transactions">No se encontraron statements en el archivo.</p>';
  } else {
    data.statements.forEach((stmt, idx) => renderStatement(stmt, idx + 1));
  }

  previewSec.classList.remove('hidden');
}

function renderStatement(stmt, num) {
  const block = document.createElement('div');
  block.className = 'statement-block';

  // Head
  block.innerHTML = `
    <div class="statement-head">
      <div class="statement-head__title">Statement #${num} — Ref: ${escapeHtml(stmt.transaction_reference)}</div>
      <div class="statement-meta">
        <span><strong>Cuenta:</strong> ${escapeHtml(stmt.iban || stmt.account_id)}</span>
        ${stmt.bic ? `<span><strong>BIC:</strong> ${escapeHtml(stmt.bic)}</span>` : ''}
        ${stmt.currency ? `<span><strong>Moneda:</strong> ${escapeHtml(stmt.currency)}</span>` : ''}
        ${stmt.statement_number ? `<span><strong>N° Extracto:</strong> ${escapeHtml(stmt.statement_number)}/${escapeHtml(stmt.sequence_number)}</span>` : ''}
        <span><strong>Transacciones:</strong> ${stmt.transactions ? stmt.transactions.length : 0}</span>
      </div>
    </div>`;

  // Balances
  const balances = [];
  if (stmt.opening_balance) balances.push({ label: 'Saldo inicial', bal: stmt.opening_balance });
  if (stmt.closing_balance) balances.push({ label: 'Saldo final', bal: stmt.closing_balance });
  if (stmt.available_balance) balances.push({ label: 'Saldo disponible', bal: stmt.available_balance });

  if (balances.length) {
    const row = document.createElement('div');
    row.className = 'balance-row';
    balances.forEach(({ label, bal }) => {
      const isCredit = bal.indicator === 'C';
      row.innerHTML += `
        <div class="balance-pill">
          <span class="balance-pill__label">${label}:</span>
          <span class="balance-pill__amount balance-pill__amount--${isCredit ? 'credit' : 'debit'}">
            ${isCredit ? '+' : '-'}${formatAmount(bal.amount)} ${escapeHtml(bal.currency)}
          </span>
          <span style="color:var(--color-muted);font-size:11px;margin-left:4px;">${bal.date}</span>
        </div>`;
    });
    block.appendChild(row);
  }

  // Transactions table
  const tableWrap = document.createElement('div');
  tableWrap.className = 'table-wrap';

  if (!stmt.transactions || stmt.transactions.length === 0) {
    tableWrap.innerHTML = '<p class="no-transactions">Sin transacciones en este statement.</p>';
  } else {
    const table = document.createElement('table');
    table.className = 'transactions-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th>#</th>
          <th>Fecha valor</th>
          <th>Fecha contable</th>
          <th>Tipo</th>
          <th>Tipo SWIFT</th>
          <th>Referencia cliente</th>
          <th>Ref. banco</th>
          <th style="text-align:right">Importe</th>
          <th>Narrativa / Detalle</th>
        </tr>
      </thead>`;

    const tbody = document.createElement('tbody');
    stmt.transactions.forEach((txn, i) => {
      const ind = indicatorLabel(txn.indicator);
      const amtClass = ind.cls === 'credit' ? 'credit' : (ind.cls === 'debit' ? 'debit' : 'debit');
      const badgeCls = `badge-ind--${ind.cls}`;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--color-muted);font-size:12px">${i + 1}</td>
        <td>${escapeHtml(txn.value_date || '-')}</td>
        <td>${escapeHtml(txn.booking_date || '-')}</td>
        <td><span class="badge-ind ${badgeCls}">${escapeHtml(ind.label)}</span></td>
        <td class="td-ref">${escapeHtml(txn.transaction_type_id || '-')}</td>
        <td class="td-ref">${escapeHtml(txn.customer_reference || '-')}</td>
        <td class="td-ref">${escapeHtml(txn.bank_reference || '-')}</td>
        <td class="td-amount td-amount--${amtClass}">${formatAmount(txn.amount)}</td>
        <td class="td-narrative">${escapeHtml(txn.narrative || '')}</td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
  }
  block.appendChild(tableWrap);
  stmtsContainer.appendChild(block);
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------
async function parseFile() {
  if (!selectedFile) return;

  clearMessages();
  hidePreview();
  showLoading('Analizando archivo MT940...');
  btnParse.disabled = true;

  const fd = new FormData();
  fd.append('file', selectedFile);

  try {
    const res = await fetch('/api/parse', { method: 'POST', body: fd });
    const data = await res.json();
    hideLoading();

    if (!res.ok) {
      showMessage('error', data.error || 'Error al procesar el archivo.', data.details);
      return;
    }

    lastParseResult = data;

    // Show errors and warnings
    if (data.errors && data.errors.length) {
      showMessage('error', `Se encontraron ${data.errors.length} error(es) al parsear:`, data.errors);
    }
    if (data.warnings && data.warnings.length) {
      showMessage('warning', `Advertencias (${data.warnings.length}):`, data.warnings);
    }
    if (data.statements && data.statements.length > 0) {
      if (!data.errors || !data.errors.length) {
        showMessage('info', `Archivo analizado correctamente: ${data.statements.length} statement(s) encontrado(s).`);
      }
      renderPreview(data);
      btnDownload.classList.remove('hidden');
      btnDownload.disabled = false;
    } else {
      showMessage('error', 'No se encontraron statements válidos en el archivo.');
    }
  } catch (err) {
    hideLoading();
    showMessage('error', 'Error de red o del servidor.', [err.message]);
  } finally {
    btnParse.disabled = false;
  }
}

async function downloadXml() {
  if (!selectedFile) return;

  showLoading('Generando camt.053 XML...');
  btnDownload.disabled = true;

  const fd = new FormData();
  fd.append('file', selectedFile);

  try {
    const res = await fetch('/api/convert', { method: 'POST', body: fd });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ error: 'Error desconocido del servidor.' }));
      hideLoading();
      showMessage('error', errData.error || 'Error al convertir.', errData.details);
      return;
    }

    // Trigger download from the blob response
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const nameMatch = disposition.match(/filename="?([^"]+)"?/);
    const downloadName = nameMatch ? nameMatch[1] : 'output_camt053.xml';

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    hideLoading();
  } catch (err) {
    hideLoading();
    showMessage('error', 'Error al descargar el archivo.', [err.message]);
  } finally {
    btnDownload.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Event listeners — Drop zone
// ---------------------------------------------------------------------------
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

fileRemove.addEventListener('click', clearFile);

// ---------------------------------------------------------------------------
// Event listeners — Buttons
// ---------------------------------------------------------------------------
btnParse.addEventListener('click', parseFile);
btnDownload.addEventListener('click', downloadXml);

// ---------------------------------------------------------------------------
// Keyboard: allow drop zone activation with Enter/Space
// ---------------------------------------------------------------------------
dropZone.setAttribute('tabindex', '0');
dropZone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
