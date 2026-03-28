"""Tests for the MT940 parser."""
import os
from datetime import date
from decimal import Decimal

import pytest

from app.parser import MT940Parser
from app.parser.models import Balance, ParseResult, Statement, Transaction

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return f.read()


class TestSingleStatement:
    def setup_method(self):
        self.parser = MT940Parser()
        self.result = self.parser.parse(read_fixture('sample_single.mt940'), 'sample_single.mt940')

    def test_no_errors(self):
        assert self.result.errors == []

    def test_one_statement(self):
        assert len(self.result.statements) == 1

    def test_statement_fields(self):
        stmt = self.result.statements[0]
        assert stmt.transaction_reference == 'STMT20240101001'
        assert stmt.related_reference == 'NONREF'
        assert stmt.iban == 'DE89370400440532013000'
        assert stmt.bic == 'COBADEFFXXX'
        assert stmt.statement_number == '00001'
        assert stmt.sequence_number == '001'
        assert stmt.currency == 'EUR'

    def test_opening_balance(self):
        bal = self.result.statements[0].opening_balance
        assert bal is not None
        assert bal.indicator == 'C'
        assert bal.date == date(2024, 1, 1)
        assert bal.currency == 'EUR'
        assert bal.amount == Decimal('10000.00')
        assert bal.balance_type == 'OPBD'

    def test_closing_balance(self):
        bal = self.result.statements[0].closing_balance
        assert bal is not None
        assert bal.indicator == 'C'
        assert bal.date == date(2024, 1, 3)
        assert bal.amount == Decimal('10300.00')
        assert bal.balance_type == 'CLBD'

    def test_available_balance(self):
        bal = self.result.statements[0].available_balance
        assert bal is not None
        assert bal.balance_type == 'FWAV'

    def test_two_transactions(self):
        assert len(self.result.statements[0].transactions) == 2

    def test_credit_transaction(self):
        txn = self.result.statements[0].transactions[0]
        assert txn.indicator == 'C'
        assert txn.amount == Decimal('500.00')
        assert txn.transaction_type_id == 'NTRF'
        assert txn.customer_reference == 'CUST-REF-001'
        assert txn.bank_reference == 'BANK-REF-001'
        assert 'ACME Corp' in txn.narrative

    def test_debit_transaction(self):
        txn = self.result.statements[0].transactions[1]
        assert txn.indicator == 'D'
        assert txn.amount == Decimal('200.00')
        assert txn.transaction_type_id == 'NCHK'
        # :86: uses ?XX sub-fields — purpose should be extracted
        assert txn.narrative is not None
        assert 'factura' in txn.narrative.lower() or '2024-001' in txn.narrative


class TestMultiStatement:
    def setup_method(self):
        self.parser = MT940Parser()
        self.result = self.parser.parse(read_fixture('sample_multi.mt940'), 'sample_multi.mt940')

    def test_no_errors(self):
        assert self.result.errors == []

    def test_two_statements(self):
        assert len(self.result.statements) == 2

    def test_first_statement(self):
        stmt = self.result.statements[0]
        assert stmt.iban == 'ES7921000813610123456789'
        assert stmt.bic == 'CAIXESBB'
        assert len(stmt.transactions) == 2

    def test_second_statement(self):
        stmt = self.result.statements[1]
        assert stmt.transaction_reference == 'STMT20240201001'
        assert len(stmt.transactions) == 3

    def test_structured_narrative(self):
        # Second statement, first transaction has ?20/?21 sub-fields
        txn = self.result.statements[1].transactions[0]
        assert txn.narrative is not None
        assert 'ABC' in txn.narrative or 'INV' in txn.narrative


class TestEdgeCases:
    def setup_method(self):
        self.parser = MT940Parser()

    def test_crlf_line_endings(self):
        text = ':20:REFTEST\r\n:21:NONREF\r\n:25:GB29NWBK60161331926819\r\n:28C:00001/001\r\n:60F:C240101GBP1000,00\r\n:62F:C240101GBP1000,00\r\n-\r\n'
        result = self.parser.parse(text, 'test.mt940')
        assert result.errors == []
        assert len(result.statements) == 1

    def test_no_bic(self):
        text = ':20:REF001\n:21:NONREF\n:25:GB29NWBK60161331926819\n:28C:1/1\n:60F:C240101GBP500,00\n:62F:C240101GBP500,00\n-\n'
        result = self.parser.parse(text, 'test.mt940')
        stmt = result.statements[0]
        assert stmt.bic is None
        assert stmt.iban == 'GB29NWBK60161331926819'

    def test_missing_transaction_ref_error(self):
        text = ':25:DE89370400440532013000\n:28C:1/1\n:60F:C240101EUR100,00\n:62F:C240101EUR100,00\n-\n'
        result = self.parser.parse(text, 'bad.mt940')
        assert len(result.errors) > 0

    def test_empty_file(self):
        result = self.parser.parse('', 'empty.mt940')
        assert len(result.errors) > 0

    def test_amount_with_comma(self):
        text = ':20:REF001\n:21:NONREF\n:25:DE89370400440532013000/COBADEFFXXX\n:28C:1/1\n:60F:C240101EUR1234567,89\n:62F:C240101EUR1234567,89\n-\n'
        result = self.parser.parse(text, 'test.mt940')
        assert result.errors == []
        assert result.statements[0].opening_balance.amount == Decimal('1234567.89')

    def test_debit_opening_balance(self):
        text = ':20:REF001\n:21:NONREF\n:25:DE89370400440532013000\n:28C:1/1\n:60F:D240101EUR500,00\n:62F:D240101EUR500,00\n-\n'
        result = self.parser.parse(text, 'test.mt940')
        assert result.statements[0].opening_balance.indicator == 'D'
