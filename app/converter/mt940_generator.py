"""
MT940 Generator

Converts a ParseResult (from Camt053Parser or MT940Parser) into a valid
SWIFT MT940 Customer Statement Message text.

Specification: SWIFT MT940 SR 2022+

Field mapping:
  :20:  Statement.transaction_reference
  :21:  Statement.related_reference (NONREF if absent)
  :25:  IBAN/BIC or account_id/BIC
  :28C: statement_number/sequence_number
  :60F: opening_balance
  :61:  Each Transaction  (value date, booking date, D/C, amount, type, refs)
  :86:  Transaction.narrative (if present)
  :62F: closing_balance
  :64:  available_balance (if present)

MT940 formatting rules applied:
  - Amounts: comma as decimal separator, no trailing zeros beyond 2 dp
  - Dates: YYMMDD (6 digits) for balances; YYMMDD+MMDD for :61:
  - Line length: no hard limit enforced (SWIFT allows 65 chars/line in :86:,
    but most bank systems accept longer lines; we wrap :86: at 65 chars)
  - Encoding: UTF-8
"""

from decimal import Decimal
from typing import Optional

from ..parser.models import Balance, ParseResult, Statement, Transaction


def _fmt_date_yymmdd(d) -> str:
    """Format a date as YYMMDD."""
    return d.strftime('%y%m%d')


def _fmt_date_mmdd(d) -> str:
    """Format a date as MMDD."""
    return d.strftime('%m%d')


def _fmt_amount(amount: Decimal) -> str:
    """
    Format a Decimal amount as MT940 amount string.
    Uses comma as decimal separator.  Always 2 decimal places.
    e.g. Decimal('1234.56') → '1234,56'
         Decimal('1000')    → '1000,00'
    """
    formatted = f'{amount:.2f}'
    return formatted.replace('.', ',')


def _balance_indicator(indicator: str) -> str:
    """Map internal indicator ('C'/'D') to MT940 single char."""
    return 'C' if indicator.upper() in ('C', 'RC', 'CN', 'CRDT') else 'D'


def _txn_indicator(indicator: str) -> str:
    """
    Map internal indicator to MT940 :61: debit/credit mark.
    MT940 valid values: C, D, RC, RD
    """
    ind = indicator.upper()
    if ind in ('RC',):
        return 'RC'
    if ind in ('RD',):
        return 'RD'
    if ind in ('C', 'CN', 'CRDT'):
        return 'C'
    return 'D'


def _wrap_86(text: str, max_line: int = 65) -> str:
    """
    Split narrative text into :86: continuation lines.
    SWIFT :86: allows up to 6 lines of 65 characters each.
    Lines after the first are prefixed with nothing (multiline field value).
    Returns a single string that, when written after ':86:', forms a valid field.
    """
    lines = []
    while text:
        lines.append(text[:max_line])
        text = text[max_line:]
        if len(lines) >= 6:
            break  # MT940 :86: max 6 × 65 chars
    return '\n'.join(lines)


class MT940Generator:
    """Generates MT940 text from a ParseResult."""

    def generate(self, parse_result: ParseResult) -> str:
        """
        Convert all statements in parse_result to MT940 text.
        Multiple statements are separated by the MT940 '-' block separator.
        """
        blocks = [self._generate_statement(stmt) for stmt in parse_result.statements]
        return '\n'.join(blocks)

    # ------------------------------------------------------------------
    # Statement block
    # ------------------------------------------------------------------

    def _generate_statement(self, stmt: Statement) -> str:
        lines = []

        # :20: Transaction Reference Number (max 16 chars, no spaces)
        ref = (stmt.transaction_reference or 'NOTPROVIDED')[:16].replace(' ', '-')
        lines.append(f':20:{ref}')

        # :21: Related Reference
        rel_ref = (stmt.related_reference or 'NONREF')[:16]
        lines.append(f':21:{rel_ref}')

        # :25: Account Identification
        lines.append(f':25:{self._fmt_account(stmt)}')

        # :28C: Statement Number / Sequence Number
        stmt_num = (stmt.statement_number or '1').lstrip('0') or '1'
        seq_num  = (stmt.sequence_number or '1').lstrip('0') or '1'
        lines.append(f':28C:{stmt_num}/{seq_num}')

        # :60F: Opening Balance
        if stmt.opening_balance:
            lines.append(self._fmt_balance('60F', stmt.opening_balance))
        elif stmt.closing_balance:
            # Fallback: use closing balance as opening when opening is missing
            lines.append(self._fmt_balance('60F', stmt.closing_balance))
        else:
            # Generate a zero balance placeholder
            ccy = stmt.currency or 'EUR'
            from datetime import date
            lines.append(f':60F:C{_fmt_date_yymmdd(date.today())}{ccy}0,00')

        # :61: + :86: per transaction
        for txn in stmt.transactions:
            lines.append(self._fmt_transaction(txn))
            if txn.narrative:
                lines.append(f':86:{_wrap_86(txn.narrative)}')

        # :62F: Closing Balance
        if stmt.closing_balance:
            lines.append(self._fmt_balance('62F', stmt.closing_balance))
        elif stmt.opening_balance:
            lines.append(self._fmt_balance('62F', stmt.opening_balance))
        else:
            ccy = stmt.currency or 'EUR'
            from datetime import date
            lines.append(f':62F:C{_fmt_date_yymmdd(date.today())}{ccy}0,00')

        # :64: Available Balance (optional)
        if stmt.available_balance:
            lines.append(self._fmt_balance('64', stmt.available_balance))

        # Block separator
        lines.append('-')

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Field formatters
    # ------------------------------------------------------------------

    def _fmt_account(self, stmt: Statement) -> str:
        """
        Format :25: value.
        Preferred: IBAN/BIC. Fallback: account_id/BIC or just account_id.
        """
        account = stmt.iban or stmt.account_id or 'NOTPROVIDED'
        if stmt.bic:
            return f'{account}/{stmt.bic}'
        return account

    def _fmt_balance(self, tag: str, bal: Balance) -> str:
        """
        Format a balance field.
        Pattern: :[tag]:[C|D]YYMMDDCCCNNN,NN
        """
        ind  = _balance_indicator(bal.indicator)
        dt   = _fmt_date_yymmdd(bal.date)
        ccy  = bal.currency or 'EUR'
        amt  = _fmt_amount(bal.amount)
        return f':{tag}:{ind}{dt}{ccy}{amt}'

    def _fmt_transaction(self, txn: Transaction) -> str:
        """
        Format a :61: statement line.
        Pattern: YYMMDD[MMDD][R]C/D amount SWIFT-type customer-ref[//bank-ref]
        """
        val_date = _fmt_date_yymmdd(txn.value_date)

        # Booking date: only include MMDD if different from value date
        if txn.booking_date and txn.booking_date != txn.value_date:
            book_date = _fmt_date_mmdd(txn.booking_date)
        else:
            book_date = ''

        ind  = _txn_indicator(txn.indicator)
        amt  = _fmt_amount(txn.amount)
        ttype = (txn.transaction_type_id or 'NTRF')[:4].upper()

        # Customer reference: max 16 chars, no slashes, no newlines
        cust_ref = (txn.customer_reference or 'NONREF')[:16].replace('/', '-').replace('\n', '')
        if not cust_ref:
            cust_ref = 'NONREF'

        line = f':61:{val_date}{book_date}{ind}{amt}{ttype}{cust_ref}'

        # Bank reference: appended after // if present
        if txn.bank_reference:
            bank_ref = txn.bank_reference[:16].replace('/', '-').replace('\n', '')
            line += f'//{bank_ref}'

        return line
