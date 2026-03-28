"""
MT940 Parser — SWIFT MT940 Customer Statement Message

Parses MT940 text files into structured Python objects.
Follows SWIFT MT940 specification (SR 2022+).

Field tags supported:
  :20:  Transaction Reference Number
  :21:  Related Reference
  :25:  Account Identification
  :28C: Statement Number / Sequence Number
  :60F: Opening Balance (Final)
  :60M: Opening Balance (Midday)
  :61:  Statement Line (transaction)
  :86:  Information to Account Owner (narrative)
  :62F: Closing Balance (Final)
  :62M: Closing Balance (Midday)
  :64:  Available Balance
  :65:  Future Value Date Balance
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from .models import Balance, ParseResult, Statement, Transaction


class MT940ParseError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Compiled regular expressions
# ---------------------------------------------------------------------------

# Splits an MT940 file into individual statement blocks.
# A lone hyphen on its own line is the block separator.
_BLOCK_SEPARATOR = re.compile(r'\n-\s*(?=\n|$)')

# Extracts all tagged fields from a single statement block.
# Captures the tag name and everything until the next tag, separator, or EOF.
_FIELD_RE = re.compile(
    r':(\d{2}[A-Z]?):(.*?)(?=:\d{2}[A-Z]?:|\Z)',
    re.DOTALL,
)

# :25: Account / BIC
_IBAN_RE = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{4,30}$')
_BIC_RE = re.compile(r'^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?$')

# :28C: Statement number / sequence number
_STMT_NUM_RE = re.compile(r'^(\d+)/(\d+)$')

# :60x:/:62x:/:64:/:65: Balance fields
# Format: [C|D] YYMMDD CCC NNN,NN
_BALANCE_RE = re.compile(
    r'^(?P<ind>[CD])'
    r'(?P<date>\d{6})'
    r'(?P<ccy>[A-Z]{3})'
    r'(?P<amount>[\d,]+)$'
)

# :61: Statement Line
# Value date (6), optional booking date (4 = MMDD), C/D/RC/RD indicator,
# amount (digits + comma), 4-char transaction type, customer ref, optional //bank_ref
_TXN_RE = re.compile(
    r'^(?P<val_date>\d{6})'
    r'(?P<book_date>\d{4})?'
    r'(?P<ind>R?[CD]N?)'
    r'(?P<amount>[\d,]+)'
    r'(?P<type>[A-Z]{4})'
    r'(?P<cust_ref>[^\n/]{0,16})'
    r'(?:\/\/(?P<bank_ref>[^\n]{0,16}))?'
    r'(?:\n(?P<supplementary>.*))?$',
    re.DOTALL,
)

# :86: sub-field codes (German banking / DTA convention)
_SUBFIELD_RE = re.compile(r'\?(\d{2})([^\?]*)')


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize line endings and strip BOM."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.lstrip('\ufeff')  # strip UTF-8 BOM if present
    return text


def _parse_date_yymmdd(yymmdd: str) -> date:
    """Parse a 6-digit YYMMDD date string. Years 00-30 → 2000-2030."""
    yy = int(yymmdd[0:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    yyyy = 2000 + yy if yy <= 30 else 1900 + yy
    return date(yyyy, mm, dd)


def _parse_booking_date(mmdd: str, value_date: date) -> date:
    """
    Parse a 4-digit MMDD booking date relative to a value date.
    Handles year wrap: if booking month is December but value month is January,
    the booking year is value_year - 1.
    """
    mm = int(mmdd[0:2])
    dd = int(mmdd[2:4])
    year = value_date.year
    # If booking month is significantly later than value month, it belongs to the prior year
    if mm > value_date.month + 1:
        year -= 1
    # If booking month is significantly earlier than value month, it belongs to the next year
    elif mm < value_date.month - 1:
        year += 1
    return date(year, mm, dd)


def _parse_amount(raw: str) -> Decimal:
    """Convert MT940 amount string (comma decimal separator) to Decimal."""
    return Decimal(raw.replace(',', '.'))


def _parse_balance(raw: str, balance_type: str) -> Balance:
    """Parse a balance field value into a Balance object."""
    raw = raw.strip()
    m = _BALANCE_RE.match(raw)
    if not m:
        raise MT940ParseError(f"Cannot parse balance value: {raw!r}")
    return Balance(
        indicator=m.group('ind'),
        date=_parse_date_yymmdd(m.group('date')),
        currency=m.group('ccy'),
        amount=_parse_amount(m.group('amount')),
        balance_type=balance_type,
    )


def _parse_account(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parse the :25: field value.
    Returns (account_id, iban_or_None, bic_or_None).
    """
    raw = raw.strip()
    # May contain BIC after last '/'
    parts = raw.split('/')
    if len(parts) >= 2:
        account_part = '/'.join(parts[:-1])
        bic_candidate = parts[-1].strip()
        bic = bic_candidate if _BIC_RE.match(bic_candidate) else None
        if not bic:
            account_part = raw
    else:
        account_part = raw
        bic = None

    account_id = account_part.strip()
    iban = account_id if _IBAN_RE.match(account_id) else None
    return account_id, iban, bic


def _parse_narrative(raw: str) -> str:
    """
    Parse :86: field. If it contains ?XX sub-fields (DTA/MT940 structured format),
    concatenate purpose sub-fields (?20–?29) as the primary remittance text.
    Falls back to the raw text.
    """
    raw = raw.strip()
    sub_fields = dict(_SUBFIELD_RE.findall(raw))
    if not sub_fields:
        return raw

    # Sub-fields ?20–?29: payment purpose / remittance information
    purpose_parts = [sub_fields[f'{i:02d}'] for i in range(20, 30) if f'{i:02d}' in sub_fields]
    if purpose_parts:
        return ''.join(purpose_parts).strip()
    # Fallback: concatenate all sub-field values
    return ' '.join(sub_fields.values()).strip() or raw


def _parse_transaction(raw: str, seq: int) -> Transaction:
    """Parse a :61: field value into a Transaction object."""
    raw = raw.strip()
    m = _TXN_RE.match(raw)
    if not m:
        raise MT940ParseError(f"Cannot parse transaction line: {raw!r}")

    value_date = _parse_date_yymmdd(m.group('val_date'))
    book_date_raw = m.group('book_date')
    booking_date = _parse_booking_date(book_date_raw, value_date) if book_date_raw else None

    indicator = m.group('ind')
    amount = _parse_amount(m.group('amount'))
    txn_type = m.group('type')
    cust_ref = m.group('cust_ref').strip() if m.group('cust_ref') else ''
    bank_ref_raw = m.group('bank_ref')
    bank_ref = bank_ref_raw.strip() if bank_ref_raw else None
    supplementary = m.group('supplementary')
    narrative = supplementary.strip() if supplementary else None

    return Transaction(
        value_date=value_date,
        booking_date=booking_date,
        indicator=indicator,
        amount=amount,
        transaction_type_id=txn_type,
        customer_reference=cust_ref,
        bank_reference=bank_ref,
        narrative=narrative,
        sequence_number=seq,
    )


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

class MT940Parser:
    """Parses MT940 text content into a ParseResult."""

    def parse(self, text: str, filename: str = '') -> ParseResult:
        text = _normalize(text)
        blocks = self._split_blocks(text)
        statements: List[Statement] = []
        errors: List[str] = []
        warnings: List[str] = []

        for i, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            try:
                stmt = self._parse_block(block)
                statements.append(stmt)
                warnings.extend(stmt.parse_warnings)
            except MT940ParseError as exc:
                errors.append(f"Block {i + 1}: {exc}")

        if not statements and not errors:
            errors.append("No MT940 statement blocks found in file.")

        return ParseResult(
            statements=statements,
            raw_text=text,
            filename=filename,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _split_blocks(self, text: str) -> List[str]:
        """Split file text into individual statement blocks on '-' separator."""
        # Handle leading {1:...}{2:...}{4:\n ... \n-} SWIFT envelope if present
        # Strip envelope wrappers (block 1/2/3/5 headers)
        text = re.sub(r'\{[0-9]:[^}]*\}', '', text)
        blocks = _BLOCK_SEPARATOR.split(text)
        return blocks

    def _extract_fields(self, block: str) -> List[Tuple[str, str]]:
        """Extract (tag, value) pairs from a statement block."""
        return [(m.group(1), m.group(2)) for m in _FIELD_RE.finditer(block)]

    def _parse_block(self, block: str) -> Statement:
        fields = self._extract_fields(block)
        if not fields:
            raise MT940ParseError("Block contains no recognisable MT940 fields.")

        stmt = Statement(
            transaction_reference='',
            related_reference=None,
            account_id='',
            iban=None,
            bic=None,
            currency=None,
            statement_number='',
            sequence_number='',
            opening_balance=None,
            closing_balance=None,
            available_balance=None,
            transactions=[],
            parse_warnings=[],
        )

        current_txn: Optional[Transaction] = None

        for tag, raw_value in fields:
            value = raw_value.strip()

            if tag == '20':
                stmt.transaction_reference = value

            elif tag == '21':
                stmt.related_reference = value

            elif tag == '25':
                account_id, iban, bic = _parse_account(value)
                stmt.account_id = account_id
                stmt.iban = iban
                stmt.bic = bic

            elif tag == '28C':
                m = _STMT_NUM_RE.match(value)
                if m:
                    stmt.statement_number = m.group(1)
                    stmt.sequence_number = m.group(2)
                else:
                    stmt.statement_number = value
                    stmt.sequence_number = '0'
                    stmt.parse_warnings.append(f":28C: unexpected format: {value!r}")

            elif tag in ('60F', '60M'):
                try:
                    stmt.opening_balance = _parse_balance(value, 'OPBD')
                    if not stmt.currency:
                        stmt.currency = stmt.opening_balance.currency
                except MT940ParseError as exc:
                    stmt.parse_warnings.append(str(exc))

            elif tag == '61':
                try:
                    current_txn = _parse_transaction(value, len(stmt.transactions))
                    stmt.transactions.append(current_txn)
                except MT940ParseError as exc:
                    stmt.parse_warnings.append(str(exc))
                    current_txn = None

            elif tag == '86':
                if current_txn is not None:
                    # If :61: already captured supplementary text, append :86: to it
                    narrative_86 = _parse_narrative(value)
                    if current_txn.narrative:
                        current_txn.narrative = f"{current_txn.narrative} {narrative_86}".strip()
                    else:
                        current_txn.narrative = narrative_86
                else:
                    stmt.parse_warnings.append(":86: found without preceding :61: — ignored.")

            elif tag in ('62F', '62M'):
                try:
                    stmt.closing_balance = _parse_balance(value, 'CLBD')
                    if not stmt.currency:
                        stmt.currency = stmt.closing_balance.currency
                except MT940ParseError as exc:
                    stmt.parse_warnings.append(str(exc))

            elif tag == '64':
                try:
                    stmt.available_balance = _parse_balance(value, 'FWAV')
                    if not stmt.currency:
                        stmt.currency = stmt.available_balance.currency
                except MT940ParseError as exc:
                    stmt.parse_warnings.append(str(exc))

            elif tag == '65':
                # Future value date balance — informational, skip storing separately
                pass

            else:
                stmt.parse_warnings.append(f"Unknown field :{tag}: — ignored.")

        if not stmt.transaction_reference:
            raise MT940ParseError("Missing mandatory field :20: (Transaction Reference Number).")
        if not stmt.account_id:
            raise MT940ParseError("Missing mandatory field :25: (Account Identification).")

        return stmt
