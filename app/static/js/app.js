/* =========================================================
   Conversor MT → MX — lógica de la interfaz
   ========================================================= */
'use strict';

// ---------------------------------------------------------------------------
// Definición de los flujos de conversión
// ---------------------------------------------------------------------------
const FLOWS = {
  'excel': {
    title: 'Cartola Excel',
    desc: 'Convierte una cartola bancaria en Excel al formato estándar que necesites.',
    note: 'Formatos: .xlsx · .xls',
    accept: '.xlsx,.xls',
    exts: ['xlsx', 'xls'],
    parseUrl: '/api/parse-excel',
    convertUrl: '/api/convert-excel',
    analyzeLabel: 'Analizar cartola',
    convertLabel: 'Generar archivo',
    hasTarget: true,
    from: 'Excel',
    samples: [
      { file: 'cartola_santander_demo.xlsx',  label: 'Cartola estilo Santander' },
      { file: 'cartola_bancochile_demo.xlsx', label: 'Cartola estilo Banco de Chile' },
      { file: 'cartola_falabella_demo.xlsx',  label: 'Cartola estilo Falabella' },
    ],
  },
  'mt-to-xml': {
    title: 'MT940 → camt.053',
    desc: 'Lee un extracto SWIFT MT940 y genera el XML ISO 20022 camt.053.001.08.',
    note: 'Formatos: .txt · .sta · .mt940 · .mt9 · .swift',
    accept: '.txt,.sta,.mt940,.mt9,.swift',
    exts: ['txt', 'sta', 'mt940', 'mt9', 'swift'],
    parseUrl: '/api/parse',
    convertUrl: '/api/convert',
    analyzeLabel: 'Analizar archivo',
    convertLabel: 'Generar camt.053 XML',
    hasTarget: false,
    from: 'MT940',
    to: 'camt.053 XML',
    samples: [{ file: 'ejemplo_mt940.txt', label: 'Extracto MT940 de ejemplo' }],
  },
  'xml-to-mt': {
    title: 'camt.053 → MT940',
    desc: 'Lee un XML ISO 20022 camt.053 y lo exporta como extracto SWIFT MT940.',
    note: 'Formato: .xml (camt.053.001.02 – .001.11)',
    accept: '.xml',
    exts: ['xml'],
    parseUrl: '/api/parse-xml',
    convertUrl: '/api/convert-xml',
    analyzeLabel: 'Analizar archivo',
    convertLabel: 'Generar MT940',
    hasTarget: false,
    from: 'camt.053 XML',
    to: 'MT940',
    samples: [{ file: 'ejemplo_camt053.xml', label: 'camt.053 de ejemplo' }],
  },
};

const TARGET_LABEL = { xml: 'camt.053 XML', mt940: 'MT940' };

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------
const state = {
  flow: 'excel',
  target: 'xml',
  file: null,
  parsed: null,
  output: null,   // { blob, text, name, truncated }
};

// ---------------------------------------------------------------------------
// Referencias al DOM
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

const sidebar     = $('sidebar');
const scrim       = $('scrim');
const flowTitle   = $('flow-title');
const flowDesc    = $('flow-desc');
const flowPipe    = $('flow-pipe');
const sourceNote  = $('source-note');
const dropzone    = $('dropzone');
const fileInput   = $('file-input');
const filecard    = $('filecard');
const fileNameEl  = $('file-name');
const fileSizeEl  = $('file-size');
const samplesWrap = $('samples-chips');
const targetField = $('target-field');
const targetSel   = $('target-select');
const btnAnalyze  = $('btn-analyze');
const btnAnalyzeL = $('btn-analyze-label');
const stepReview  = $('step-review');
const reviewMeta  = $('review-meta');
const kpisEl      = $('kpis');
const noticesEl   = $('notices');
const stmtsEl     = $('statements');
const btnConvert  = $('btn-convert');
const btnConvertL = $('btn-convert-label');
const stepOutput  = $('step-output');
const outputMeta  = $('output-meta');
const outputName  = $('output-name');
const outputCode  = $('output-code');
const btnCopy     = $('btn-copy');
const btnDownload = $('btn-download');
const dropveil    = $('dropveil');
const toastsEl    = $('toasts');
const formatsModal= $('formats-modal');

const PREVIEW_LIMIT = 300000;

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtBytes(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(2)} MB`;
}

// Monedas sin subunidad: mostrarlas con decimales sería ruido.
const ZERO_DECIMAL = new Set(['CLP', 'JPY', 'KRW', 'ISK', 'PYG', 'VND', 'COP',
                              'XOF', 'XAF', 'XPF', 'GNF', 'RWF', 'UGX', 'KMF', 'DJF', 'BIF']);

function fmtMoney(v, ccy) {
  const n = Number(v);
  if (!isFinite(n)) return String(v ?? '');
  const d = ZERO_DECIMAL.has(String(ccy || '').toUpperCase()) ? 0 : 2;
  return n.toLocaleString('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).split('-');
  return (y && m && d) ? `${d}-${m}-${y}` : iso;
}

function extOf(name) {
  return name.includes('.') ? name.split('.').pop().toLowerCase() : '';
}

/** Dirección contable efectiva de un movimiento. */
function direction(ind) {
  switch (String(ind || '').toUpperCase()) {
    case 'C':  return 'credit';
    case 'RD': return 'credit';   // reverso de un cargo → suma
    case 'D':  return 'debit';
    case 'RC': return 'debit';    // reverso de un abono → resta
    default:   return 'debit';
  }
}

function indicatorTag(ind) {
  switch (String(ind || '').toUpperCase()) {
    case 'C':  return { label: 'Abono',    cls: 'credit' };
    case 'D':  return { label: 'Cargo',    cls: 'debit' };
    case 'RC': return { label: 'Rev. abono', cls: 'reversal' };
    case 'RD': return { label: 'Rev. cargo', cls: 'reversal' };
    default:   return { label: ind || '—', cls: 'debit' };
  }
}

const ICON = {
  ok:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  err:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>',
  info:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>',
  warn:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  file:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/></svg>',
};

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------
function toast(kind, message, ms = 4200) {
  const el = document.createElement('div');
  el.className = `toast toast--${kind}`;
  const icon = kind === 'success' ? ICON.ok : kind === 'error' ? ICON.err : ICON.info;
  el.innerHTML = `<span class="toast__icon">${icon}</span><span>${esc(message)}</span>`;
  toastsEl.appendChild(el);
  setTimeout(() => {
    el.classList.add('is-out');
    setTimeout(() => el.remove(), 180);
  }, ms);
}

// ---------------------------------------------------------------------------
// Tema
// ---------------------------------------------------------------------------
const themeSeg = $('theme-seg');

/** 'system' quita el atributo para que mande prefers-color-scheme. */
function applyTheme(choice) {
  if (choice === 'system') {
    document.documentElement.removeAttribute('data-theme');
    try { localStorage.removeItem('mtmx-theme'); } catch (e) {}
  } else {
    document.documentElement.setAttribute('data-theme', choice);
    try { localStorage.setItem('mtmx-theme', choice); } catch (e) {}
  }
  themeSeg.querySelectorAll('.theme__opt').forEach((o) => {
    o.setAttribute('aria-checked', String(o.dataset.themeChoice === choice));
  });
}

themeSeg.querySelectorAll('.theme__opt').forEach((opt) => {
  opt.addEventListener('click', () => applyTheme(opt.dataset.themeChoice));
});

(function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem('mtmx-theme'); } catch (e) {}
  applyTheme(stored === 'dark' || stored === 'light' ? stored : 'system');
})();

// ---------------------------------------------------------------------------
// Barra lateral (móvil)
// ---------------------------------------------------------------------------
function setSidebar(open) {
  sidebar.classList.toggle('is-open', open);
  scrim.hidden = !open;
  $('menu-btn').setAttribute('aria-expanded', String(open));
}
$('menu-btn').addEventListener('click', () => setSidebar(true));
$('sidebar-close').addEventListener('click', () => setSidebar(false));
scrim.addEventListener('click', () => setSidebar(false));

// ---------------------------------------------------------------------------
// Modal de formatos
// ---------------------------------------------------------------------------
$('btn-formats').addEventListener('click', () => { formatsModal.showModal(); setSidebar(false); });
$('formats-close').addEventListener('click', () => formatsModal.close());
formatsModal.addEventListener('click', (e) => {
  if (e.target === formatsModal) formatsModal.close();   // clic en el backdrop
});

// ---------------------------------------------------------------------------
// Cambio de flujo
// ---------------------------------------------------------------------------
function renderPipe() {
  const f = FLOWS[state.flow];
  const to = f.hasTarget ? TARGET_LABEL[state.target] : f.to;
  flowPipe.innerHTML =
    `<span class="pipe__tag">${esc(f.from)}</span>` +
    `<svg class="pipe__arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13M13 6l6 6-6 6"/></svg>` +
    `<span class="pipe__tag pipe__tag--out">${esc(to)}</span>`;
}

function renderSamples() {
  const f = FLOWS[state.flow];
  samplesWrap.innerHTML = '';
  f.samples.forEach((s) => {
    const b = document.createElement('button');
    b.className = 'chip';
    b.type = 'button';
    b.innerHTML = `${ICON.file}<span>${esc(s.label)}</span>`;
    b.addEventListener('click', () => loadSample(s.file));
    samplesWrap.appendChild(b);
  });
}

function setFlow(flow, opts = {}) {
  if (!FLOWS[flow]) return;
  state.flow = flow;
  const f = FLOWS[flow];

  document.querySelectorAll('.nav__item[data-flow]').forEach((el) => {
    const on = el.dataset.flow === flow;
    el.classList.toggle('is-active', on);
    if (on) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });

  flowTitle.textContent = f.title;
  flowDesc.textContent = f.desc;
  sourceNote.textContent = f.note;
  fileInput.accept = f.accept;
  btnAnalyzeL.textContent = f.analyzeLabel;
  btnConvertL.textContent = f.convertLabel;
  targetField.hidden = !f.hasTarget;

  renderPipe();
  renderSamples();
  if (!opts.keepFile) clearFile();
  setSidebar(false);
}

document.querySelectorAll('.nav__item[data-flow]').forEach((el) => {
  el.addEventListener('click', () => setFlow(el.dataset.flow));
});

// Formato de salida (solo flujo Excel)
targetSel.querySelectorAll('.segmented__opt').forEach((opt) => {
  opt.addEventListener('click', () => {
    state.target = opt.dataset.target;
    targetSel.querySelectorAll('.segmented__opt').forEach((o) => {
      const on = o === opt;
      o.classList.toggle('is-active', on);
      o.setAttribute('aria-checked', String(on));
    });
    renderPipe();
    btnConvertL.textContent = `Generar ${TARGET_LABEL[state.target]}`;
    hideOutput();
    // Los límites de formato dependen del destino elegido.
    if (state.parsed) { renderNotices(state.parsed); renderFormatLimits(state.parsed); }
  });
});

// ---------------------------------------------------------------------------
// Manejo del archivo
// ---------------------------------------------------------------------------
function flowForExt(ext) {
  for (const [key, f] of Object.entries(FLOWS)) {
    if (f.exts.includes(ext)) return key;
  }
  return null;
}

// Debe coincidir con MAX_UPLOAD_MB en el servidor. Si se supera, Flask responde
// un 413 en HTML que no se puede leer como JSON, así que se avisa antes de subir.
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

/** Lee la respuesta como JSON; si no lo es (413/500 en HTML), devuelve un error legible. */
async function readJson(res) {
  try {
    return await res.json();
  } catch (e) {
    if (res.status === 413) {
      return { error: `El archivo supera el máximo de ${fmtBytes(MAX_UPLOAD_BYTES)} admitido.` };
    }
    return { error: `El servidor respondió de forma inesperada (HTTP ${res.status}).` };
  }
}

function setFile(file) {
  if (file.size > MAX_UPLOAD_BYTES) {
    toast('error', `«${file.name}» pesa ${fmtBytes(file.size)} y el máximo es ${fmtBytes(MAX_UPLOAD_BYTES)}.`);
    return;
  }

  const ext = extOf(file.name);
  const belongs = FLOWS[state.flow].exts.includes(ext);

  if (!belongs) {
    const target = flowForExt(ext);
    if (target) {
      setFlow(target, { keepFile: true });
      toast('info', `Se cambió a «${FLOWS[target].title}» según el tipo de archivo.`);
    } else {
      toast('error', `Tipo de archivo no admitido (.${ext}).`);
      return;
    }
  }

  state.file = file;
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = fmtBytes(file.size);
  filecard.hidden = false;
  dropzone.hidden = true;
  btnAnalyze.disabled = false;
  hideReview();
  hideOutput();
}

function clearFile() {
  state.file = null;
  state.parsed = null;
  fileInput.value = '';
  filecard.hidden = true;
  dropzone.hidden = false;
  btnAnalyze.disabled = true;
  hideReview();
  hideOutput();
}

$('file-remove').addEventListener('click', clearFile);

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

// Arrastrar y soltar en toda la ventana
let dragDepth = 0;
window.addEventListener('dragenter', (e) => {
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
  dragDepth++;
  dropveil.hidden = false;
});
window.addEventListener('dragover', (e) => { e.preventDefault(); });
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropveil.hidden = true;
});
window.addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  dropveil.hidden = true;
  const file = e.dataTransfer?.files?.[0];
  if (file) setFile(file);
});

// ---------------------------------------------------------------------------
// Ejemplos
// ---------------------------------------------------------------------------
async function loadSample(name) {
  try {
    const res = await fetch(`/static/samples/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    setFile(new File([blob], name, { type: blob.type }));
    toast('success', `Ejemplo «${name}» cargado.`);
  } catch (err) {
    toast('error', `No se pudo cargar el ejemplo: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Estados de los pasos
// ---------------------------------------------------------------------------
function hideReview() {
  stepReview.hidden = true;
  stmtsEl.innerHTML = '';
  noticesEl.innerHTML = '';
  kpisEl.innerHTML = '';
  $('interpretation').innerHTML = '';
  reviewMeta.textContent = '';
}
function hideOutput() { stepOutput.hidden = true; outputCode.textContent = ''; state.output = null; }

function busy(btn, on) { btn.classList.toggle('is-busy', on); btn.disabled = on; }

function reveal(el) {
  el.hidden = false;
  requestAnimationFrame(() => el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
}

// ---------------------------------------------------------------------------
// Render: KPIs
// ---------------------------------------------------------------------------
function renderKpis(data) {
  const stmts = data.statements || [];
  const txns = stmts.flatMap((s) => s.transactions || []);

  let credits = 0, debits = 0, nCredits = 0, nDebits = 0;
  txns.forEach((t) => {
    const amt = Number(t.amount) || 0;
    if (direction(t.indicator) === 'credit') { credits += amt; nCredits++; }
    else { debits += amt; nDebits++; }
  });

  const dates = txns.map((t) => t.value_date).filter(Boolean).sort();
  const period = dates.length
    ? (dates[0] === dates[dates.length - 1]
        ? fmtDate(dates[0])
        : `${fmtDate(dates[0])} → ${fmtDate(dates[dates.length - 1])}`)
    : '—';

  const last = stmts[stmts.length - 1];
  const closing = last && last.closing_balance;
  const ccy = (last && last.currency) || (closing && closing.currency) || '';

  const cards = [
    {
      label: 'Movimientos',
      value: String(txns.length),
      sub: stmts.length > 1 ? `en ${stmts.length} statements` : period,
    },
    {
      label: 'Abonos',
      value: `+${fmtMoney(credits, ccy)}`,
      cls: 'credit',
      sub: `${nCredits} movimiento${nCredits === 1 ? '' : 's'}`,
    },
    {
      label: 'Cargos',
      value: `−${fmtMoney(debits, ccy)}`,
      cls: 'debit',
      sub: `${nDebits} movimiento${nDebits === 1 ? '' : 's'}`,
    },
  ];

  if (closing) {
    const isC = closing.indicator === 'C';
    cards.push({
      label: 'Saldo de cierre',
      value: `${isC ? '' : '−'}${fmtMoney(closing.amount, closing.currency || ccy)} ${closing.currency || ccy}`,
      cls: isC ? 'credit' : 'debit',
      sub: fmtDate(closing.date),
    });
  }

  kpisEl.innerHTML = cards.map((c) => `
    <div class="kpi">
      <div class="kpi__label">${esc(c.label)}</div>
      <div class="kpi__value${c.cls ? ` kpi__value--${c.cls}` : ''}">${esc(c.value)}</div>
      <div class="kpi__sub">${esc(c.sub || '')}</div>
    </div>`).join('');
}

// ---------------------------------------------------------------------------
// Render: avisos
// ---------------------------------------------------------------------------
function addNotice(kind, title, items) {
  const el = document.createElement('div');
  el.className = `notice notice--${kind}`;
  const list = (items && items.length)
    ? `<ul class="notice__list">${items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul>` : '';
  el.innerHTML =
    `<span class="notice__icon">${kind === 'error' ? ICON.err : ICON.warn}</span>` +
    `<div class="notice__body"><strong>${esc(title)}</strong>${list}</div>`;
  noticesEl.appendChild(el);
}

/** El campo :86: de MT940 admite 6 líneas de 65 caracteres: más allá se pierde. */
const MT940_NARRATIVE_MAX = 6 * 65;

function willOutputMt940() {
  return state.flow === 'xml-to-mt' || (state.flow === 'excel' && state.target === 'mt940');
}

function renderFormatLimits(data) {
  if (!willOutputMt940()) return;
  const over = (data.statements || [])
    .flatMap((s) => s.transactions || [])
    .filter((t) => (t.narrative || '').length > MT940_NARRATIVE_MAX);
  if (!over.length) return;

  addNotice('warning',
    `${over.length} movimiento${over.length === 1 ? ' tiene un detalle' : 's tienen un detalle'} ` +
    `más largo de lo que admite MT940`,
    [`El campo :86: acepta 6 líneas de 65 caracteres (${MT940_NARRATIVE_MAX} en total); ` +
     `el texto sobrante se recortará en el archivo generado. ` +
     `Si necesitas conservarlo completo, exporta a camt.053 XML.`]);
}

function renderNotices(data) {
  noticesEl.innerHTML = '';
  const add = addNotice;

  if (data.errors && data.errors.length) {
    add('error', `${data.errors.length} error${data.errors.length === 1 ? '' : 'es'} de lectura`, data.errors);
  }
  const warns = [
    ...(data.warnings || []),
    ...(data.statements || []).flatMap((s) => s.parse_warnings || []),
  ];
  const uniq = [...new Set(warns)];
  if (uniq.length) {
    add('warning', `${uniq.length} advertencia${uniq.length === 1 ? '' : 's'}`, uniq);
  }
}

// ---------------------------------------------------------------------------
// Render: cómo se leyó el archivo y qué se dio por supuesto
// ---------------------------------------------------------------------------
function renderInterpretation(data) {
  const box = $('interpretation');
  box.innerHTML = '';
  const meta = data.meta || {};
  const map = meta.field_map || [];
  const notes = meta.assumptions || [];
  if (!map.length && !notes.length) return;

  const rows = map.map((f) => `
    <tr${f.used ? '' : ' class="is-unused"'}>
      <td class="td-ref">${esc(f.column)}</td>
      <td>${esc(f.header || '—')}</td>
      <td>${esc(f.label)}</td>
      <td class="td-use">${f.used ? 'Se usa' : 'No se usa'}</td>
    </tr>`).join('');

  box.innerHTML = `
    <details class="reading">
      <summary class="reading__summary">
        <svg class="reading__chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
        <span>Cómo se leyó tu archivo</span>
        <span class="reading__badge">${map.length} columna${map.length === 1 ? '' : 's'} · ${notes.length} supuesto${notes.length === 1 ? '' : 's'}</span>
      </summary>
      <div class="reading__body">
        ${map.length ? `
        <p class="reading__lead">Cabecera detectada en la fila ${esc(meta.header_row ?? '—')}. Cada columna se interpretó así:</p>
        <div class="tablewrap tablewrap--plain">
          <table class="txns reading__table">
            <thead><tr><th>Col.</th><th>Cabecera del archivo</th><th>Se interpretó como</th><th>Estado</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>` : ''}
        ${notes.length ? `
        <p class="reading__lead">Valores que la cartola no trae y se dedujeron:</p>
        <ul class="reading__notes">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
      </div>
    </details>`;
}

// ---------------------------------------------------------------------------
// Cuadre: apertura + movimientos debe dar el saldo de cierre
// ---------------------------------------------------------------------------
function balanceCheck(s) {
  if (!s.opening_balance || !s.closing_balance) return null;
  const signed = (b) => (b.indicator === 'C' ? 1 : -1) * Number(b.amount);
  const moves = (s.transactions || []).reduce(
    (a, t) => a + (direction(t.indicator) === 'credit' ? 1 : -1) * Number(t.amount), 0);
  const expected = signed(s.opening_balance) + moves;
  const delta = Math.round((signed(s.closing_balance) - expected) * 100) / 100;
  return { ok: Math.abs(delta) < 0.005, delta };
}

// ---------------------------------------------------------------------------
// Render: statements
// ---------------------------------------------------------------------------
function renderStatements(data) {
  stmtsEl.innerHTML = '';
  const stmts = data.statements || [];

  stmts.forEach((s, idx) => {
    const box = document.createElement('div');
    box.className = 'stmt';

    const facts = [];
    if (s.iban || s.account_id) facts.push(['Cuenta', s.iban || s.account_id]);
    if (s.bic) facts.push(['BIC', s.bic]);
    if (s.currency) facts.push(['Moneda', s.currency]);
    if (s.statement_number) facts.push(['Extracto', `${s.statement_number}/${s.sequence_number}`]);

    const bals = [
      ['Saldo inicial', s.opening_balance],
      ['Saldo final', s.closing_balance],
      ['Disponible', s.available_balance],
    ].filter(([, b]) => b);

    const txns = s.transactions || [];

    box.innerHTML = `
      <div class="stmt__head">
        <div class="stmt__ref">Statement ${idx + 1} · <span>${esc(s.transaction_reference || '—')}</span></div>
        <div class="stmt__facts">
          ${facts.map(([k, v]) => `<span>${esc(k)}: <b>${esc(v)}</b></span>`).join('')}
        </div>
      </div>
      ${bals.length ? `<div class="balances">${bals.map(([label, b]) => {
        const isC = b.indicator === 'C';
        return `<span class="bal">
          <span class="bal__label">${esc(label)}</span>
          <span class="bal__amt bal__amt--${isC ? 'credit' : 'debit'}">${isC ? '' : '−'}${fmtMoney(b.amount, b.currency)} ${esc(b.currency)}</span>
          <span class="bal__date">${fmtDate(b.date)}</span>
        </span>`;
      }).join('')}${(() => {
        const chk = balanceCheck(s);
        if (!chk) return '';
        return chk.ok
          ? `<span class="bal bal--ok" title="Saldo inicial + movimientos = saldo final">
               ${ICON.ok}<span class="bal__label">Cuadra</span></span>`
          : `<span class="bal bal--bad" title="El saldo final declarado no coincide con la suma de los movimientos">
               ${ICON.warn}<span class="bal__label">Descuadre de</span>
               <span class="bal__amt">${fmtMoney(Math.abs(chk.delta), s.currency)} ${esc(s.currency || '')}</span></span>`;
      })()}</div>` : ''}
      <div class="stmt__tools">
        <label class="search">
          ${ICON.search}
          <input type="search" placeholder="Filtrar movimientos…" aria-label="Filtrar movimientos" />
        </label>
        <span class="stmt__count"></span>
      </div>
      <div class="tablewrap">
        ${txns.length ? `
        <table class="txns">
          <thead><tr>
            <th class="num">#</th>
            <th>F. valor</th>
            <th>F. contable</th>
            <th>Tipo</th>
            <th>Código</th>
            <th>Ref. cliente</th>
            <th>Ref. banco</th>
            <th class="num">Importe</th>
            <th>Detalle</th>
          </tr></thead>
          <tbody>${txns.map((t, i) => {
            const tag = indicatorTag(t.indicator);
            const dir = direction(t.indicator);
            const hay = [t.value_date, t.booking_date, t.transaction_type_id,
                         t.customer_reference, t.bank_reference, t.narrative, t.amount]
                        .filter(Boolean).join(' ').toLowerCase();
            return `<tr data-hay="${esc(hay)}">
              <td class="td-i num" style="text-align:right">${i + 1}</td>
              <td class="td-date">${fmtDate(t.value_date)}</td>
              <td class="td-date">${t.booking_date ? fmtDate(t.booking_date) : '—'}</td>
              <td><span class="tag tag--${tag.cls}">${esc(tag.label)}</span></td>
              <td class="td-ref">${esc(t.transaction_type_id || '—')}</td>
              <td class="td-ref">${esc(t.customer_reference || '—')}</td>
              <td class="td-ref">${esc(t.bank_reference || '—')}</td>
              <td class="td-amt td-amt--${dir}">${dir === 'credit' ? '+' : '−'}${fmtMoney(t.amount, s.currency)}</td>
              <td class="td-desc">${esc(t.narrative || '')}</td>
            </tr>`;
          }).join('')}</tbody>
        </table>` : '<p class="empty">Este statement no tiene movimientos.</p>'}
      </div>`;

    stmtsEl.appendChild(box);

    // Filtro por statement
    const input = box.querySelector('.search input');
    const count = box.querySelector('.stmt__count');
    const rows = Array.from(box.querySelectorAll('tbody tr'));
    const setCount = (n) => {
      count.textContent = n === txns.length
        ? `${txns.length} movimiento${txns.length === 1 ? '' : 's'}`
        : `${n} de ${txns.length}`;
    };
    setCount(txns.length);
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach((r) => {
        const hit = !q || r.dataset.hay.includes(q);
        r.hidden = !hit;
        if (hit) shown++;
      });
      setCount(shown);
    });
  });
}

// ---------------------------------------------------------------------------
// Paso 1 → 2 : analizar
// ---------------------------------------------------------------------------
btnAnalyze.addEventListener('click', async () => {
  if (!state.file) return;
  const f = FLOWS[state.flow];
  busy(btnAnalyze, true);
  hideOutput();

  const fd = new FormData();
  fd.append('file', state.file);

  try {
    const res = await fetch(f.parseUrl, { method: 'POST', body: fd });
    const data = await readJson(res);

    if (!res.ok) {
      hideReview();
      toast('error', data.error || 'No se pudo analizar el archivo.');
      if (data.details && data.details.length) {
        stepReview.hidden = false;
        renderNotices({ errors: data.details, warnings: [] });
      }
      return;
    }

    state.parsed = data;
    renderKpis(data);
    renderNotices(data);
    renderFormatLimits(data);
    renderInterpretation(data);
    renderStatements(data);

    const n = (data.statements || []).length;
    const total = (data.statements || []).reduce((a, s) => a + (s.transactions || []).length, 0);
    reviewMeta.textContent = `${n} statement${n === 1 ? '' : 's'} · ${total} movimiento${total === 1 ? '' : 's'}`;

    if (!n) {
      stmtsEl.innerHTML = '<p class="empty">No se encontraron statements en el archivo.</p>';
      btnConvert.disabled = true;
      toast('error', 'No se encontraron statements válidos.');
    } else {
      btnConvert.disabled = false;
      toast('success', `${total} movimiento${total === 1 ? '' : 's'} leído${total === 1 ? '' : 's'} correctamente.`);
    }
    reveal(stepReview);
  } catch (err) {
    toast('error', `Error de red: ${err.message}`);
  } finally {
    busy(btnAnalyze, false);
  }
});

// ---------------------------------------------------------------------------
// Paso 2 → 3 : convertir
// ---------------------------------------------------------------------------
btnConvert.addEventListener('click', async () => {
  if (!state.file) return;
  const f = FLOWS[state.flow];
  busy(btnConvert, true);

  const fd = new FormData();
  fd.append('file', state.file);
  if (f.hasTarget) fd.append('target', state.target);

  try {
    const res = await fetch(f.convertUrl, { method: 'POST', body: fd });

    if (!res.ok) {
      const err = await readJson(res);
      toast('error', err.error || 'No se pudo generar el archivo.');
      return;
    }

    const blob = await res.blob();
    const disp = res.headers.get('Content-Disposition') || '';
    const name = (disp.match(/filename="?([^"]+)"?/) || [])[1] || 'resultado.txt';
    const text = await blob.text();

    const truncated = text.length > PREVIEW_LIMIT;
    state.output = { blob, text, name, truncated };

    outputName.textContent = name;
    outputCode.textContent = truncated
      ? `${text.slice(0, PREVIEW_LIMIT)}\n\n… vista previa truncada. Descarga el archivo para verlo completo.`
      : text;

    const lines = text.split('\n').length;
    outputMeta.textContent = `${fmtBytes(blob.size)} · ${lines.toLocaleString('es-CL')} líneas`;

    reveal(stepOutput);
    toast('success', 'Archivo generado. Revísalo y descárgalo.');
  } catch (err) {
    toast('error', `Error de red: ${err.message}`);
  } finally {
    busy(btnConvert, false);
  }
});

// ---------------------------------------------------------------------------
// Paso 3 : copiar y descargar
// ---------------------------------------------------------------------------
btnCopy.addEventListener('click', async () => {
  if (!state.output) return;
  const text = state.output.text;
  try {
    await navigator.clipboard.writeText(text);
    toast('success', 'Contenido copiado al portapapeles.');
  } catch (e) {
    // Reserva para contextos sin acceso al portapapeles
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand && document.execCommand('copy');
    ta.remove();
    toast(ok ? 'success' : 'error', ok ? 'Contenido copiado.' : 'No se pudo copiar.');
  }
});

btnDownload.addEventListener('click', () => {
  if (!state.output) return;
  const url = URL.createObjectURL(state.output.blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = state.output.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------
setFlow('excel');
