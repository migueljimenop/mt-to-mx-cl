"""
Excel (cartola bancaria) Parser

Parses bank statement Excel files (.xlsx / .xls) into the same internal
model (ParseResult / Statement / Transaction / Balance) used by the MT940
and camt.053 parsers, so the existing generators can produce output.

The parser is layout-agnostic: it detects the header row and maps columns
by their (normalised) names, so it accepts heterogeneous cartolas from
different banks automatically. Known layouts all work:

  * Banco Falabella  — single signed "MONTO" column (credit = negative),
                       header on row 1.
  * Banco Santander  — separate "Monto cargo" / "Monto abono" columns + "Saldo".
  * Banco de Chile   — separate "Cargos" / "Abonos" columns + "Saldo" (.xls).

Only transactions are extracted. Opening/closing balances are derived from
the net of the transactions so that the generated MT940/camt.053 files are
internally consistent.
"""

import io
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from .models import Balance, ParseResult, Statement, Transaction

DEFAULT_CURRENCY = 'CLP'

# ---------------------------------------------------------------------------
# Header / column detection keywords (normalised: no accents, lowercase)
# ---------------------------------------------------------------------------

_IGNORE_KW = ('cuota', 'titular', 'adicional', 'canal', 'sucursal', 'rut')

_DEBIT_KW = ('cargo',)
_CREDIT_KW = ('abono',)
_BALANCE_KW = ('saldo',)
_DATE_KW = ('fecha',)
_DESCRIPTION_KW = ('detalle', 'descripcion', 'concepto', 'observacion')
_AMOUNT_KW = ('monto', 'importe', 'amount', 'valor')

# Any cell containing a date keyword is treated as "the date" column.
# A statement header row must contain at least a date and a description.
_MAX_HEADER_SCAN = 40


def _norm(value: str) -> str:
    """Normalise a header cell: lowercase, strip accents, keep alnum/space."""
    value = value.lower()
    value = ''.join(
        c for c in unicodedata.normalize('NFD', value)
        if unicodedata.category(c) != 'Mn'
    )
    return ''.join(c for c in value if c.isalnum() or c == ' ')


def _contains_kw(norm: str, kws: Tuple[str, ...]) -> bool:
    return any(k in norm for k in kws)


def _classify(norm: str) -> Optional[str]:
    """Return the semantic role for a header cell, or None if ignored/blank."""
    if not norm:
        return None
    if _contains_kw(norm, _IGNORE_KW):
        return None
    if _contains_kw(norm, _DEBIT_KW):
        return 'debit'
    if _contains_kw(norm, _CREDIT_KW):
        return 'credit'
    if _contains_kw(norm, _BALANCE_KW):
        return 'balance'
    if _contains_kw(norm, _DATE_KW):
        return 'date'
    if _contains_kw(norm, _DESCRIPTION_KW):
        return 'description'
    if _contains_kw(norm, _AMOUNT_KW):
        return 'amount'
    return None


def _row_roles(row: List) -> List[str]:
    return [_classify(_norm('' if v is None else str(v))) for v in row]


def _find_header(rows: List[List]) -> int:
    """Return the index of the first row that looks like a header table."""
    for i, row in enumerate(rows[:_MAX_HEADER_SCAN]):
        roles = _row_roles(row)
        if 'date' in roles and 'description' in roles and len(roles) >= 2:
            return i
    return -1


# ---------------------------------------------------------------------------
# Loading .xlsx / .xls into rows of raw values
# ---------------------------------------------------------------------------

def _load_rows(filename: str, data: bytes) -> List[List]:
    """Load the first worksheet of an .xlsx/.xls file into raw cell values."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext == 'xls':
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        sh = wb.sheet_by_index(0)
        rows: List[List] = []
        for r in range(sh.nrows):
            rows.append([sh.cell_value(r, c) for c in range(sh.ncols)])
        return rows

    # default: openpyxl (.xlsx / .xlsm / generic)
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# ---------------------------------------------------------------------------
# Cell parsing helpers
# ---------------------------------------------------------------------------

def _to_number(value) -> Optional[Decimal]:
    """Coerce a cell (int/float/str) into a Decimal, or None if invalid."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return Decimal('1') if value else Decimal('0')
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip().replace('$', '').replace(' ', '')
    if text in ('', '-', '—', '–'):
        return None
    # Assume '.' is a thousands separator and ',' the decimal separator.
    text = text.replace('.', '').replace(',', '.')
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_date(value) -> Optional[date]:
    """Parse an Excel cell date (datetime, int serial-less str, or str)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y',
                '%d/%m/%y', '%d-%m-%y', '%m/%d/%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _number_at(row: List, idx: Optional[int]) -> Optional[Decimal]:
    """Number at ``idx``, or None if the column is absent or the row is short."""
    if idx is None or idx >= len(row):
        return None
    return _to_number(row[idx])


def _cell_string(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


# ---------------------------------------------------------------------------
# Metadata extraction (account / currency) from pre-header rows
# ---------------------------------------------------------------------------

def _col_letter(idx: int) -> str:
    """Spreadsheet column label for a zero-based index (0 -> A, 26 -> AA)."""
    label = ''
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        label = chr(65 + rem) + label
    return label


def _extract_metadata(rows: List[List], header_idx: int) -> Tuple[str, str, bool]:
    """Return (account_id, currency, currency_found) from the pre-header rows."""
    currency = DEFAULT_CURRENCY
    currency_found = False
    account_id = 'NOTPROVIDED'
    for row in rows[:header_idx]:
        for c, cell in enumerate(row):
            if cell is None:
                continue
            text = str(cell).lower()
            if not currency_found and ('pesos' in text or 'clp' in text):
                currency = 'CLP'
                currency_found = True
            if 'cuenta' in text and ':' in text and account_id == 'NOTPROVIDED':
                owned = text.split(':', 1)[1].strip()
                candidate = owned or ''
                if not candidate:
                    # Account number in the next cell of the same row
                    for nxt in row[c + 1:]:
                        if nxt is not None and str(nxt).strip():
                            candidate = str(nxt).strip()
                            break
                if candidate and account_id == 'NOTPROVIDED':
                    account_id = candidate
    return account_id, currency, currency_found


# ---------------------------------------------------------------------------
# Reporting: how the sheet was read, and what had to be assumed
# ---------------------------------------------------------------------------

_ROLE_LABEL = {
    'date':        'Fecha del movimiento',
    'description': 'Detalle',
    'debit':       'Cargo',
    'credit':      'Abono',
    'amount':      'Monto con signo',
    'balance':     'Saldo',
}


def _describe_field_map(header: List, cols: dict) -> List[dict]:
    """Describe which spreadsheet column was read as which role."""
    described = []
    for role, idx in sorted(cols.items(), key=lambda kv: kv[1]):
        raw = header[idx] if idx < len(header) else None
        described.append({
            'role': role,
            'label': _ROLE_LABEL.get(role, role),
            'column': _col_letter(idx),
            'header': _cell_string(raw),
            'used': role != 'balance',
        })
    return described


def _describe_assumptions(cols: dict, currency: str, currency_found: bool,
                          account_id: str) -> List[str]:
    """List the values the parser had to invent, in the UI's language."""
    notes = [
        'La cartola no declara saldo de apertura: se asume 0 y el saldo de '
        'cierre se deriva del neto de los movimientos.',
        'Las fechas de los saldos se toman del primer y del último movimiento.',
        'El origen no trae código de operación: cada movimiento se emite como '
        'NTRF (transferencia).',
    ]
    if 'balance' in cols:
        notes.append(
            'La columna «Saldo» del archivo no se utiliza: los saldos se '
            'recalculan a partir de los movimientos.'
        )
    if not currency_found:
        notes.append(f'No se encontró la moneda en el archivo: se asume {currency}.')
    if account_id == 'NOTPROVIDED':
        notes.append(
            'No se encontró el número de cuenta: se emite NOTPROVIDED, valor '
            'admitido por el estándar cuando la cuenta no está disponible.'
        )
    return notes


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class ExcelParser:
    """Parses a bank statement Excel file into a ParseResult."""

    def parse(self, filename: str, data: bytes) -> ParseResult:
        try:
            rows = _load_rows(filename, data)
        except Exception as exc:
            return ParseResult(
                statements=[], raw_text='', filename=filename,
                errors=[f'No se pudo leer el archivo Excel: {exc}'],
            )

        header_idx = _find_header(rows)
        if header_idx < 0:
            return ParseResult(
                statements=[], raw_text='', filename=filename,
                errors=['No se encontró una fila de cabecera reconocible '
                        '(se espera una columna de fecha y una de descripción).'],
            )

        header = rows[header_idx]
        cols: dict = {}
        for idx, cells in enumerate(header):
            role = _classify(_norm('' if cells is None else str(cells)))
            if role and role not in cols:
                cols[role] = idx

        account_id, currency, currency_found = _extract_metadata(rows, header_idx)

        warnings: List[str] = []
        transactions: List[Transaction] = []
        net = Decimal('0')

        for r, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            txn, amount_signed = self._parse_row(
                row, cols, r, currency, warnings
            )
            if txn is None:
                continue
            transactions.append(txn)
            net += amount_signed

        if not transactions:
            return ParseResult(
                statements=[], raw_text='', filename=filename,
                errors=['El archivo no contiene transacciones reconocibles.'],
                warnings=warnings,
            )

        # Date the derived balances to the period the cartola actually covers,
        # not to today: downstream the camt.053 statement period (FrToDt) is
        # taken from these two dates.
        txn_dates = [t.value_date for t in transactions]
        opening = Balance('C', min(txn_dates), currency, Decimal('0'), 'OPBD')
        ind = 'D' if net < 0 else 'C'
        closing = Balance(ind, max(txn_dates), currency, abs(net), 'CLBD')

        ref = (account_id or 'NOTPROVIDED').replace(' ', '-')[:16] or 'NOTPROVIDED'
        stmt = Statement(
            transaction_reference=ref,
            related_reference=None,
            account_id=account_id,
            iban=None,
            bic=None,
            currency=currency,
            statement_number='1',
            sequence_number='1',
            opening_balance=opening,
            closing_balance=closing,
            available_balance=None,
            transactions=transactions,
            parse_warnings=list(warnings),
        )

        return ParseResult(
            statements=[stmt], raw_text=filename, filename=filename,
            errors=[], warnings=warnings,
            meta={
                'header_row': header_idx + 1,
                'field_map': _describe_field_map(header, cols),
                'assumptions': _describe_assumptions(
                    cols, currency, currency_found, account_id
                ),
            },
        )

    def _parse_row(self, row: List, cols: dict, lineno: int, ccy: str,
                   warnings: List[str]) -> Tuple[Optional[Transaction], Decimal]:
        """Parse one data row into a Transaction.

        Returns (txn, balance_effect) where balance_effect is the amount signed
        by how it moves the account balance: positive for credits, negative for
        debits.
        """
        date_idx = cols.get('date')
        if date_idx is None or date_idx >= len(row):
            return None, Decimal('0')
        d = _parse_date(row[date_idx])
        if d is None:
            return None, Decimal('0')

        indicator: Optional[str] = None
        amount: Optional[Decimal] = None

        # Membership test, not truthiness: a cargo/abono column sitting at index
        # 0 is a valid position and must not read as "no such column".
        if 'debit' in cols or 'credit' in cols:
            debit = _number_at(row, cols.get('debit'))
            credit = _number_at(row, cols.get('credit'))
            if debit:
                indicator, amount = 'D', abs(debit)
            elif credit:
                indicator, amount = 'C', abs(credit)
        elif 'amount' in cols:
            raw = _number_at(row, cols.get('amount'))
            if raw:
                indicator = 'D' if raw > 0 else 'C'
                amount = abs(raw)

        if amount is None or amount == 0 or indicator is None:
            return None, Decimal('0')

        desc_idx = cols.get('description')
        narrative = _cell_string(row[desc_idx]) if desc_idx is not None else ''

        # Signed by its effect on the balance: a credit raises it, a debit lowers
        # it. This keeps the derived closing balance consistent with the emitted
        # :61: lines (closing = opening + credits - debits).
        signed = -amount if indicator == 'D' else amount

        txn = Transaction(
            value_date=d,
            booking_date=None,
            indicator=indicator,
            amount=amount,
            transaction_type_id='NTRF',
            customer_reference='',
            bank_reference=None,
            narrative=narrative or None,
            sequence_number=0,
        )
        return txn, signed