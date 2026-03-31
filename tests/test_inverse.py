"""Tests for the inverse conversion: camt.053 XML → MT940."""
import io
import os
import re
from datetime import date
from decimal import Decimal

import pytest

from app import create_app
from app.converter import MT940Generator
from app.parser import Camt053Parser, MT940Parser
from app.parser.models import Balance, ParseResult, Statement, Transaction

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# camt.053 Parser tests
# ---------------------------------------------------------------------------

class TestCamt053Parser:

    def setup_method(self):
        self.parser = Camt053Parser()
        self.result = self.parser.parse(read_fixture('sample_camt053.xml'), 'sample_camt053.xml')

    def test_no_errors(self):
        assert self.result.errors == []

    def test_one_statement(self):
        assert len(self.result.statements) == 1

    def test_statement_fields(self):
        stmt = self.result.statements[0]
        assert stmt.transaction_reference == 'STMT20240101'
        assert stmt.iban == 'DE89370400440532013000'
        assert stmt.bic == 'COBADEFFXXX'
        assert stmt.currency == 'EUR'
        assert stmt.statement_number == '1'

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

    def test_two_transactions(self):
        assert len(self.result.statements[0].transactions) == 2

    def test_credit_transaction(self):
        txn = self.result.statements[0].transactions[0]
        assert txn.indicator == 'C'
        assert txn.amount == Decimal('500.00')
        assert txn.transaction_type_id == 'NTRF'
        assert txn.bank_reference == 'BANK-REF-001'
        assert txn.customer_reference == 'CUST-REF-001'
        assert 'ACME Corp' in txn.narrative

    def test_debit_transaction(self):
        txn = self.result.statements[0].transactions[1]
        assert txn.indicator == 'D'
        assert txn.amount == Decimal('200.00')
        assert txn.transaction_type_id == 'NCHK'
        assert '2024-001' in txn.narrative

    def test_reversal_indicator(self):
        xml = read_fixture('sample_camt053.xml').replace(
            '<RvslInd>false</RvslInd>', '<RvslInd>true</RvslInd>'
        )
        result = self.parser.parse(xml, 'test.xml')
        assert result.statements[0].transactions[0].indicator == 'RC'

    def test_invalid_xml(self):
        result = self.parser.parse('<not>valid xml', 'bad.xml')
        assert len(result.errors) > 0

    def test_wrong_document_type(self):
        xml = '<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"><CstmrCdtTrfInitn/></Document>'
        result = self.parser.parse(xml, 'wrong.xml')
        assert len(result.errors) > 0

    def test_othr_account_id(self):
        xml = read_fixture('sample_camt053.xml').replace(
            '<Id>\n          <IBAN>DE89370400440532013000</IBAN>\n        </Id>',
            '<Id><Othr><Id>ACCOUNT-12345</Id></Othr></Id>'
        )
        result = self.parser.parse(xml, 'othr.xml')
        assert result.errors == []
        stmt = result.statements[0]
        assert stmt.iban is None
        assert stmt.account_id == 'ACCOUNT-12345'


# ---------------------------------------------------------------------------
# MT940 Generator tests
# ---------------------------------------------------------------------------

class TestMT940Generator:

    def setup_method(self):
        self.parser = Camt053Parser()
        self.gen    = MT940Generator()
        self.result = self.parser.parse(read_fixture('sample_camt053.xml'), 'sample_camt053.xml')
        self.mt940  = self.gen.generate(self.result)

    def test_output_is_string(self):
        assert isinstance(self.mt940, str)
        assert len(self.mt940) > 0

    def test_has_field_20(self):
        assert ':20:' in self.mt940

    def test_has_field_25(self):
        assert ':25:' in self.mt940
        # IBAN should appear
        assert 'DE89370400440532013000' in self.mt940

    def test_bic_in_field_25(self):
        # :25:IBAN/BIC
        assert 'COBADEFFXXX' in self.mt940

    def test_has_field_28c(self):
        assert ':28C:' in self.mt940

    def test_has_field_60f(self):
        assert ':60F:' in self.mt940
        assert 'C240101EUR10000,00' in self.mt940

    def test_has_field_62f(self):
        assert ':62F:' in self.mt940
        assert 'C240103EUR10300,00' in self.mt940

    def test_transactions_in_61(self):
        lines_61 = [l for l in self.mt940.splitlines() if l.startswith(':61:')]
        assert len(lines_61) == 2

    def test_credit_transaction_61(self):
        lines_61 = [l for l in self.mt940.splitlines() if l.startswith(':61:')]
        credit = next(l for l in lines_61 if 'C500,00' in l)
        assert 'NTRF' in credit

    def test_debit_transaction_61(self):
        lines_61 = [l for l in self.mt940.splitlines() if l.startswith(':61:')]
        debit = next(l for l in lines_61 if 'D200,00' in l)
        assert 'NCHK' in debit

    def test_narrative_in_86(self):
        lines_86 = [l for l in self.mt940.splitlines() if l.startswith(':86:')]
        assert len(lines_86) == 2
        narratives = ' '.join(lines_86)
        assert 'ACME' in narratives

    def test_block_separator(self):
        assert '\n-' in self.mt940 or self.mt940.endswith('-')

    def test_amount_comma_format(self):
        # MT940 amounts must use comma as decimal separator
        assert '500,00' in self.mt940
        assert '200,00' in self.mt940
        assert '500.00' not in self.mt940

    def test_date_yymmdd_format(self):
        # Dates in :61: must be YYMMDD
        assert re.search(r':61:24010[23]', self.mt940)

    def test_bank_ref_double_slash(self):
        # Bank reference should appear after //
        assert '//BANK-REF-001' in self.mt940


# ---------------------------------------------------------------------------
# Full round-trip: MT940 → camt.053 → MT940
# ---------------------------------------------------------------------------

class TestRoundTrip:

    def test_mt940_to_camt_to_mt940(self):
        """Parsing MT940 → generating camt.053 → parsing camt.053 → generating MT940
        should produce structurally equivalent data."""
        from app.converter import Camt053Generator
        mt_parser   = MT940Parser()
        xml_gen     = Camt053Generator()
        xml_parser  = Camt053Parser()
        mt_gen      = MT940Generator()

        # Step 1: MT940 → parse
        mt_result = mt_parser.parse(read_fixture('sample_single.mt940'), 'single.mt940')
        assert mt_result.errors == []

        # Step 2: → camt.053 XML
        xml_str = xml_gen.generate(mt_result)
        assert '<?xml' in xml_str

        # Step 3: camt.053 → parse
        xml_result = xml_parser.parse(xml_str, 'round_trip.xml')
        assert xml_result.errors == [], xml_result.errors

        # Step 4: → MT940
        mt940_out = mt_gen.generate(xml_result)

        # Structural checks on the output
        assert ':20:' in mt940_out
        assert ':60F:' in mt940_out
        assert ':62F:' in mt940_out

        stmt_orig = mt_result.statements[0]
        stmt_rt   = xml_result.statements[0]

        # Account preserved
        assert stmt_rt.iban == stmt_orig.iban

        # Transaction count preserved
        assert len(stmt_rt.transactions) == len(stmt_orig.transactions)

        # Amounts preserved (as Decimal)
        for orig, rt in zip(stmt_orig.transactions, stmt_rt.transactions):
            assert rt.amount == orig.amount
            assert rt.indicator == orig.indicator


# ---------------------------------------------------------------------------
# Flask route tests for inverse endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def upload_xml(client, endpoint, filename):
    with open(os.path.join(FIXTURES, filename), 'rb') as f:
        data = f.read()
    return client.post(
        endpoint,
        data={'file': (io.BytesIO(data), filename)},
        content_type='multipart/form-data',
    )


class TestInverseRoutes:

    def test_parse_xml_returns_json(self, client):
        resp = upload_xml(client, '/api/parse-xml', 'sample_camt053.xml')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['errors'] == []
        assert data['statement_count'] == 1

    def test_parse_xml_statement_fields(self, client):
        resp = upload_xml(client, '/api/parse-xml', 'sample_camt053.xml')
        stmt = resp.get_json()['statements'][0]
        assert stmt['iban'] == 'DE89370400440532013000'
        assert stmt['bic'] == 'COBADEFFXXX'
        assert len(stmt['transactions']) == 2

    def test_convert_xml_returns_mt940(self, client):
        resp = upload_xml(client, '/api/convert-xml', 'sample_camt053.xml')
        assert resp.status_code == 200
        assert 'text' in resp.content_type
        text = resp.data.decode('utf-8')
        assert ':20:' in text
        assert ':61:' in text

    def test_convert_xml_download_filename(self, client):
        resp = upload_xml(client, '/api/convert-xml', 'sample_camt053.xml')
        disp = resp.headers.get('Content-Disposition', '')
        assert 'mt940' in disp

    def test_parse_xml_no_file(self, client):
        resp = client.post('/api/parse-xml')
        assert resp.status_code == 400

    def test_parse_xml_wrong_extension(self, client):
        resp = client.post(
            '/api/parse-xml',
            data={'file': (io.BytesIO(b'data'), 'file.mt940')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_convert_xml_no_file(self, client):
        resp = client.post('/api/convert-xml')
        assert resp.status_code == 400
