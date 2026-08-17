"""
camt.053.001.08 XML Generator

Converts a ParseResult (from MT940Parser) into a valid
ISO 20022 BankToCustomerStatement (camt.053.001.08) XML document.

Schema: urn:iso:std:iso:20022:tech:xsd:camt.053.001.08
Reference: SWIFT MyStandards / ISO 20022 SR 2022+
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from ..parser.models import Balance, ParseResult, Statement, Transaction

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"

# Register the namespace so ET serialises clean (no ns0: prefixes)
ET.register_namespace('', NS)


def _e(parent: ET.Element, tag: str) -> ET.Element:
    """Append a child element in the camt.053 namespace."""
    return ET.SubElement(parent, f'{{{NS}}}{tag}')


def _et(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Append a child element with text content."""
    el = _e(parent, tag)
    el.text = text
    return el


def _format_datetime(dt: Optional[datetime] = None) -> str:
    """Format a datetime as ISO 8601 with UTC offset."""
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')


def _format_date(d) -> str:
    """Format a date as YYYY-MM-DD."""
    return d.isoformat()


def _format_amount(amount: Decimal) -> str:
    """Format a Decimal amount with exactly 2 decimal places."""
    return f'{amount:.2f}'


def _credit_debit(indicator: str) -> str:
    """Map MT940 indicator (C/D/RC/RD) to ISO 20022 CdtDbtInd value."""
    ind = indicator.upper()
    if ind in ('C', 'RC', 'CN'):
        return 'CRDT'
    if ind in ('D', 'RD', 'DN'):
        return 'DBIT'
    return 'CRDT'


class Camt053Generator:
    """Generates a camt.053.001.08 XML document from a ParseResult."""

    def generate(self, parse_result: ParseResult) -> str:
        """
        Convert a ParseResult into a camt.053 XML string.
        Returns the full XML document as a UTF-8 string.
        """
        root = ET.Element(f'{{{NS}}}Document')

        bks = _e(root, 'BkToCstmrStmt')
        self._add_group_header(bks, parse_result)

        for stmt in parse_result.statements:
            self._add_statement(bks, stmt)

        return self._serialize(root)

    # ------------------------------------------------------------------
    # Group Header
    # ------------------------------------------------------------------

    def _add_group_header(self, parent: ET.Element, result: ParseResult) -> None:
        grp = _e(parent, 'GrpHdr')
        _et(grp, 'MsgId', str(uuid.uuid4()).replace('-', '')[:35])
        _et(grp, 'CreDtTm', _format_datetime())

    # ------------------------------------------------------------------
    # Statement
    # ------------------------------------------------------------------

    def _add_statement(self, parent: ET.Element, stmt: Statement) -> None:
        s = _e(parent, 'Stmt')

        # Statement identification
        _et(s, 'Id', stmt.transaction_reference[:35] if stmt.transaction_reference else 'UNKNOWN')
        _et(s, 'ElctrncSeqNb', stmt.statement_number if stmt.statement_number else '1')
        _et(s, 'CreDtTm', _format_datetime())

        # Statement period (derived from opening/closing balance dates if available)
        if stmt.opening_balance and stmt.closing_balance:
            fr_to = _e(s, 'FrToDt')
            _et(fr_to, 'FrDtTm', _format_datetime(
                datetime(stmt.opening_balance.date.year,
                         stmt.opening_balance.date.month,
                         stmt.opening_balance.date.day,
                         tzinfo=timezone.utc)
            ))
            _et(fr_to, 'ToDtTm', _format_datetime(
                datetime(stmt.closing_balance.date.year,
                         stmt.closing_balance.date.month,
                         stmt.closing_balance.date.day,
                         tzinfo=timezone.utc)
            ))

        # Account
        self._add_account(s, stmt)

        # Balances
        if stmt.opening_balance:
            self._add_balance(s, stmt.opening_balance)
        if stmt.closing_balance:
            self._add_balance(s, stmt.closing_balance)
        if stmt.available_balance:
            self._add_balance(s, stmt.available_balance)

        # Transactions
        for txn in stmt.transactions:
            self._add_entry(s, txn, stmt.currency or 'EUR')

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def _add_account(self, parent: ET.Element, stmt: Statement) -> None:
        acct = _e(parent, 'Acct')
        acct_id = _e(acct, 'Id')

        if stmt.iban:
            _et(acct_id, 'IBAN', stmt.iban)
        else:
            othr = _e(acct_id, 'Othr')
            _et(othr, 'Id', stmt.account_id[:34] if stmt.account_id else 'NOTPROVIDED')

        if stmt.currency:
            _et(acct, 'Ccy', stmt.currency)

        if stmt.bic:
            svcr = _e(acct, 'Svcr')
            fin_instn = _e(svcr, 'FinInstnId')
            _et(fin_instn, 'BICFI', stmt.bic)

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def _add_balance(self, parent: ET.Element, bal: Balance) -> None:
        b = _e(parent, 'Bal')

        tp = _e(b, 'Tp')
        cd_or_prtry = _e(tp, 'CdOrPrtry')
        _et(cd_or_prtry, 'Cd', bal.balance_type)

        amt = _et(b, 'Amt', _format_amount(bal.amount))
        amt.set('Ccy', bal.currency)

        _et(b, 'CdtDbtInd', _credit_debit(bal.indicator))

        dt = _e(b, 'Dt')
        _et(dt, 'Dt', _format_date(bal.date))

    # ------------------------------------------------------------------
    # Entry (transaction)
    # ------------------------------------------------------------------

    def _add_entry(self, parent: ET.Element, txn: Transaction, default_ccy: str) -> None:
        ntry = _e(parent, 'Ntry')

        amt = _et(ntry, 'Amt', _format_amount(txn.amount))
        amt.set('Ccy', default_ccy)

        _et(ntry, 'CdtDbtInd', _credit_debit(txn.indicator))

        # Reversal flag
        is_reversal = txn.indicator.upper().startswith('R')
        _et(ntry, 'RvslInd', 'true' if is_reversal else 'false')

        sts = _e(ntry, 'Sts')
        _et(sts, 'Cd', 'BOOK')

        if txn.booking_date:
            book_dt = _e(ntry, 'BookgDt')
            _et(book_dt, 'Dt', _format_date(txn.booking_date))

        val_dt = _e(ntry, 'ValDt')
        _et(val_dt, 'Dt', _format_date(txn.value_date))

        if txn.bank_reference:
            _et(ntry, 'AcctSvcrRef', txn.bank_reference[:35])

        if txn.customer_reference:
            _et(ntry, 'NtryRef', txn.customer_reference[:35])

        # Bank transaction code
        bk_tx_cd = _e(ntry, 'BkTxCd')
        prtry = _e(bk_tx_cd, 'Prtry')
        _et(prtry, 'Cd', txn.transaction_type_id[:35] if txn.transaction_type_id else 'NTRF')
        _et(prtry, 'Issr', 'SWIFT')

        # Entry details / remittance information
        if txn.narrative:
            ntry_dtls = _e(ntry, 'NtryDtls')
            tx_dtls = _e(ntry_dtls, 'TxDtls')
            rmt_inf = _e(tx_dtls, 'RmtInf')
            # camt.053 Ustrd allows max 140 chars per element; split if needed
            narrative = txn.narrative
            while narrative:
                chunk = narrative[:140]
                narrative = narrative[140:]
                _et(rmt_inf, 'Ustrd', chunk)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _serialize(self, root: ET.Element) -> str:
        """Serialize the ElementTree to a pretty-printed XML string."""
        # Python 3.9+ has ET.indent for pretty-printing
        try:
            ET.indent(root, space='  ')
        except AttributeError:
            pass  # Python < 3.9 — output will not be indented

        # Try lxml for better pretty-printing and proper XML declaration
        try:
            import lxml.etree as lxml_et
            xml_bytes = ET.tostring(root, encoding='unicode')
            lxml_root = lxml_et.fromstring(xml_bytes.encode('utf-8'))
            result = lxml_et.tostring(
                lxml_root,
                pretty_print=True,
                xml_declaration=True,
                encoding='UTF-8',
            ).decode('utf-8')
            return result
        except ImportError:
            pass

        # Fallback: stdlib serialization
        xml_str = ET.tostring(root, encoding='unicode', xml_declaration=False)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
