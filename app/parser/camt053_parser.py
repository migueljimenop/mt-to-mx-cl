"""
camt.053 XML Parser

Parses an ISO 20022 camt.053.001.08 BankToCustomerStatement XML document
into the same internal model (ParseResult / Statement / Transaction / Balance)
used by the MT940 parser, so that the MT940 generator can produce MT940 output.

Supports:
  - camt.053.001.02 through .001.11 (namespace-agnostic element lookup)
  - IBAN and Othr account identification
  - OPBD / CLBD / FWAV / ITBD balance types
  - Multiple Stmt blocks per Document
  - Multiple Ntry (entries) per statement
  - Ustrd remittance information (concatenated)
"""

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from .models import Balance, ParseResult, Statement, Transaction

# ---------------------------------------------------------------------------
# Namespace helpers — accept any camt.053 version
# ---------------------------------------------------------------------------

_CAMT053_NS_RE = re.compile(
    r'urn:iso:std:iso:20022:tech:xsd:camt\.053\.001\.\d+'
)


def _detect_namespace(root: ET.Element) -> Optional[str]:
    """Extract the camt.053 namespace URI from the root element tag."""
    tag = root.tag  # e.g. '{urn:iso:std:...}Document'
    m = re.match(r'\{([^}]+)\}', tag)
    if m and _CAMT053_NS_RE.match(m.group(1)):
        return m.group(1)
    return None


class _NS:
    """Helper to build namespaced tag queries."""
    def __init__(self, ns: str):
        self._ns = ns

    def __call__(self, tag: str) -> str:
        return f'{{{self._ns}}}{tag}' if self._ns else tag

    def find(self, element: ET.Element, path: str) -> Optional[ET.Element]:
        """Find a single element using namespace-qualified path segments."""
        parts = path.split('/')
        current = element
        for part in parts:
            current = current.find(self(part))
            if current is None:
                return None
        return current

    def findall(self, element: ET.Element, path: str) -> List[ET.Element]:
        parts = path.split('/')
        # Walk all but the last; findall on the last
        current = element
        for part in parts[:-1]:
            current = current.find(self(part))
            if current is None:
                return []
        return current.findall(self(parts[-1]))

    def text(self, element: ET.Element, path: str, default: str = '') -> str:
        el = self.find(element, path)
        return (el.text or '').strip() if el is not None else default


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_iso_date(value: str) -> Optional[date]:
    """Parse ISO 8601 date or datetime string to a date object."""
    if not value:
        return None
    value = value.strip()
    # Try date-only first (YYYY-MM-DD)
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    # Try datetime
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Balance type mapping (ISO 20022 → internal)
# ---------------------------------------------------------------------------

_BAL_CODE_MAP = {
    'OPBD': 'OPBD',   # Opening Booked
    'CLBD': 'CLBD',   # Closing Booked
    'FWAV': 'FWAV',   # Forward Available
    'ITBD': 'ITBD',   # Interim Booked
    'PRCD': 'OPBD',   # Previous Closing → treat as opening
    'CLAV': 'FWAV',   # Closing Available → treat as available
    'ITAV': 'FWAV',   # Interim Available
}

_OPENING_CODES = {'OPBD', 'PRCD'}
_CLOSING_CODES = {'CLBD'}
_AVAILABLE_CODES = {'FWAV', 'CLAV', 'ITAV', 'ITBD'}


def _balance_type_label(code: str) -> str:
    return _BAL_CODE_MAP.get(code.upper(), code.upper())


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

def _find_date_in_choice(parent: ET.Element, outer_tag: str, ns: '_NS') -> Optional[date]:
    """
    Extract a date from a DateAndDateTimeChoice child element.
    The structure is:  <outer_tag><Dt>YYYY-MM-DD</Dt></outer_tag>
                   or  <outer_tag><DtTm>YYYY-MM-DDTHH:MM:SS</DtTm></outer_tag>
    Uses explicit child search to avoid ambiguity when inner tag name == outer tag name.
    """
    outer = parent.find(outer_tag)
    if outer is None:
        return None
    for inner_tag in (ns('Dt'), ns('DtTm')):
        inner = outer.find(inner_tag)
        if inner is not None and inner.text:
            return _parse_iso_date(inner.text.strip())
    return None


class Camt053Parser:
    """Parses a camt.053 XML string into a ParseResult."""

    def parse(self, xml_text: str, filename: str = '') -> ParseResult:
        errors: List[str] = []
        warnings: List[str] = []
        statements: List[Statement] = []

        try:
            root = ET.fromstring(xml_text.strip().encode('utf-8')
                                 if not xml_text.strip().startswith('<')
                                 else xml_text.strip())
        except ET.ParseError as exc:
            return ParseResult(
                statements=[],
                raw_text=xml_text,
                filename=filename,
                errors=[f'XML parse error: {exc}'],
            )

        ns_uri = _detect_namespace(root)
        if ns_uri is None:
            # Try without namespace (bare XML)
            ns_uri = ''
            warnings.append('Namespace not detected — attempting namespace-less parse.')

        ns = _NS(ns_uri)

        # Navigate to BkToCstmrStmt
        bks = ns.find(root, 'BkToCstmrStmt')
        if bks is None:
            return ParseResult(
                statements=[],
                raw_text=xml_text,
                filename=filename,
                errors=['Element <BkToCstmrStmt> not found. Is this a valid camt.053 document?'],
            )

        for i, stmt_el in enumerate(ns.findall(bks, 'Stmt')):
            try:
                stmt = self._parse_statement(stmt_el, ns, i + 1)
                statements.append(stmt)
                warnings.extend(stmt.parse_warnings)
            except Exception as exc:
                errors.append(f'Statement {i + 1}: {exc}')

        if not statements and not errors:
            errors.append('No <Stmt> elements found in the document.')

        return ParseResult(
            statements=statements,
            raw_text=xml_text,
            filename=filename,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Statement
    # ------------------------------------------------------------------

    def _parse_statement(self, stmt_el: ET.Element, ns: _NS, idx: int) -> Statement:
        parse_warnings: List[str] = []

        stmt_id = ns.text(stmt_el, 'Id') or f'STMT{idx:05d}'
        seq_nb  = ns.text(stmt_el, 'ElctrncSeqNb') or '1'

        # Account
        acct_el = ns.find(stmt_el, 'Acct')
        iban, account_id, bic, currency = self._parse_account(acct_el, ns, parse_warnings)

        # Balances
        opening_balance: Optional[Balance] = None
        closing_balance: Optional[Balance] = None
        available_balance: Optional[Balance] = None

        for bal_el in ns.findall(stmt_el, 'Bal'):
            bal = self._parse_balance(bal_el, ns, parse_warnings)
            if bal is None:
                continue
            if bal.balance_type in _OPENING_CODES:
                opening_balance = bal
            elif bal.balance_type in _CLOSING_CODES:
                closing_balance = bal
            elif bal.balance_type in _AVAILABLE_CODES:
                available_balance = bal
            else:
                # Unknown balance type — store as available if not set
                if available_balance is None:
                    available_balance = bal

        # Infer currency from balances if not found on account
        if not currency:
            for b in (opening_balance, closing_balance, available_balance):
                if b and b.currency:
                    currency = b.currency
                    break

        # Transactions
        transactions: List[Transaction] = []
        for j, ntry_el in enumerate(ns.findall(stmt_el, 'Ntry')):
            try:
                txn = self._parse_entry(ntry_el, ns, j, currency or '')
                transactions.append(txn)
            except Exception as exc:
                parse_warnings.append(f'Entry {j + 1}: {exc}')

        return Statement(
            transaction_reference=stmt_id[:16],
            related_reference='NONREF',
            account_id=account_id,
            iban=iban,
            bic=bic,
            currency=currency,
            statement_number=seq_nb,
            sequence_number='001',
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            available_balance=available_balance,
            transactions=transactions,
            parse_warnings=parse_warnings,
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def _parse_account(
        self,
        acct_el: Optional[ET.Element],
        ns: _NS,
        warnings: List[str],
    ) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
        """Returns (iban, account_id, bic, currency)."""
        if acct_el is None:
            warnings.append('<Acct> element missing.')
            return None, 'NOTPROVIDED', None, None

        # IBAN
        iban_el = ns.find(acct_el, 'Id/IBAN')
        iban = iban_el.text.strip() if iban_el is not None and iban_el.text else None

        # Other account ID
        othr_el = ns.find(acct_el, 'Id/Othr/Id')
        othr_id = othr_el.text.strip() if othr_el is not None and othr_el.text else None

        account_id = iban or othr_id or 'NOTPROVIDED'

        # BIC
        bic_el = ns.find(acct_el, 'Svcr/FinInstnId/BICFI')
        if bic_el is None:
            bic_el = ns.find(acct_el, 'Svcr/FinInstnId/BIC')
        bic = bic_el.text.strip() if bic_el is not None and bic_el.text else None

        # Currency
        ccy_el = ns.find(acct_el, 'Ccy')
        currency = ccy_el.text.strip() if ccy_el is not None and ccy_el.text else None

        return iban, account_id, bic, currency

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def _parse_balance(
        self,
        bal_el: ET.Element,
        ns: _NS,
        warnings: List[str],
    ) -> Optional[Balance]:
        # Balance type code
        cd_el = ns.find(bal_el, 'Tp/CdOrPrtry/Cd')
        if cd_el is None or not cd_el.text:
            warnings.append('<Bal> missing Tp/CdOrPrtry/Cd — skipped.')
            return None
        raw_type = cd_el.text.strip().upper()
        balance_type = _balance_type_label(raw_type)

        # Amount
        amt_el = ns.find(bal_el, 'Amt')
        if amt_el is None or not amt_el.text:
            warnings.append(f'<Bal> ({raw_type}) missing Amt — skipped.')
            return None
        try:
            amount = Decimal(amt_el.text.strip())
        except InvalidOperation:
            warnings.append(f'<Bal> ({raw_type}) invalid amount: {amt_el.text!r} — skipped.')
            return None
        currency = (amt_el.get('Ccy') or '').strip()

        # Credit/Debit indicator
        cdi_el = ns.find(bal_el, 'CdtDbtInd')
        indicator = 'C' if (cdi_el is None or (cdi_el.text or '').strip().upper() == 'CRDT') else 'D'

        # Date — use explicit two-step lookup to avoid issues with same-named nested tags
        bal_date = None
        outer_dt = bal_el.find(ns('Dt'))
        if outer_dt is not None:
            for inner_tag in (ns('Dt'), ns('DtTm')):
                inner = outer_dt.find(inner_tag)
                if inner is not None and inner.text:
                    bal_date = _parse_iso_date(inner.text.strip())
                    break
        if bal_date is None:
            warnings.append(f'<Bal> ({raw_type}) missing or unparseable date — using today.')
            from datetime import date as _date
            bal_date = _date.today()

        return Balance(
            indicator=indicator,
            date=bal_date,
            currency=currency,
            amount=amount,
            balance_type=balance_type,
        )

    # ------------------------------------------------------------------
    # Entry (transaction)
    # ------------------------------------------------------------------

    def _parse_entry(
        self,
        ntry_el: ET.Element,
        ns: _NS,
        seq: int,
        default_ccy: str,
    ) -> Transaction:
        # Amount
        amt_el = ns.find(ntry_el, 'Amt')
        if amt_el is None or not amt_el.text:
            raise ValueError('<Ntry> missing Amt')
        try:
            amount = Decimal(amt_el.text.strip())
        except InvalidOperation:
            raise ValueError(f'Invalid amount: {amt_el.text!r}')
        currency = (amt_el.get('Ccy') or default_ccy).strip()

        # Credit/Debit indicator
        cdi_el = ns.find(ntry_el, 'CdtDbtInd')
        cdi = (cdi_el.text or 'CRDT').strip().upper() if cdi_el is not None else 'CRDT'
        # Reversal flag
        rvsl_el = ns.find(ntry_el, 'RvslInd')
        is_reversal = rvsl_el is not None and (rvsl_el.text or '').strip().lower() == 'true'
        if cdi == 'CRDT':
            indicator = 'RC' if is_reversal else 'C'
        else:
            indicator = 'RD' if is_reversal else 'D'

        # Booking date — explicit two-step to handle DateAndDateTimeChoice
        booking_date = _find_date_in_choice(ntry_el, ns('BookgDt'), ns)

        # Value date
        value_date = _find_date_in_choice(ntry_el, ns('ValDt'), ns)
        if value_date is None:
            value_date = booking_date
        if value_date is None:
            from datetime import date as _date
            value_date = _date.today()

        # Bank reference (AcctSvcrRef)
        bank_ref_el = ns.find(ntry_el, 'AcctSvcrRef')
        bank_ref = bank_ref_el.text.strip()[:16] if bank_ref_el is not None and bank_ref_el.text else None

        # Customer reference (NtryRef)
        ntry_ref_el = ns.find(ntry_el, 'NtryRef')
        cust_ref = ntry_ref_el.text.strip()[:16] if ntry_ref_el is not None and ntry_ref_el.text else ''

        # Bank transaction code
        btc_el = ns.find(ntry_el, 'BkTxCd/Prtry/Cd')
        if btc_el is None:
            btc_el = ns.find(ntry_el, 'BkTxCd/Domn/Fmly/Cd')
        txn_type = (btc_el.text or 'NTRF').strip()[:4] if btc_el is not None else 'NTRF'

        # Narrative: collect all Ustrd elements across NtryDtls/TxDtls/RmtInf
        narrative_parts = []
        for ustrd_el in ntry_el.iter(ns('Ustrd')):
            if ustrd_el.text and ustrd_el.text.strip():
                narrative_parts.append(ustrd_el.text.strip())
        # Also check AddtlNtryInf (additional entry information)
        addtl_el = ns.find(ntry_el, 'AddtlNtryInf')
        if addtl_el is not None and addtl_el.text and addtl_el.text.strip():
            narrative_parts.append(addtl_el.text.strip())
        narrative = ' '.join(narrative_parts) or None

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
