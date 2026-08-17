"""Tests for the Excel (cartola) parser and its Flask routes."""
import io
import os
from datetime import date
from decimal import Decimal

import pytest

from app import create_app
from app.converter import Camt053Generator, MT940Generator
from app.parser import ExcelParser

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def read_fixture_bytes(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return f.read()


@pytest.fixture
def parser():
    return ExcelParser()


# ---------------------------------------------------------------------------
# Parser: Banco Falabella style (single signed MONTO column)
# ---------------------------------------------------------------------------

class TestFalabella:

    def setup_method(self):
        self.p = ExcelParser()
        self.r = self.p.parse('excel_falabella.xlsx', read_fixture_bytes('excel_falabella.xlsx'))

    def test_no_errors(self):
        assert self.r.errors == []

    def test_one_statement(self):
        assert len(self.r.statements) == 1

    def test_transaction_count(self):
        assert len(self.r.statements[0].transactions) == 3

    def test_currency(self):
        assert self.r.statements[0].currency == 'CLP'

    def test_debit_positive_amount(self):
        t = self.r.statements[0].transactions[0]
        assert t.indicator == 'D'
        assert t.amount == Decimal('23728')
        assert t.value_date == date(2026, 8, 15)

    def test_credit_negative_amount(self):
        t = self.r.statements[0].transactions[2]
        assert t.indicator == 'C'          # negative MONTO = credit (pago tarjeta)
        assert t.amount == Decimal('141281')
        assert 'PAGO TARJETA CMR' in t.narrative

    def test_closing_equals_net(self):
        s = self.r.statements[0]
        # 23728 + 4093 - 141281 = -113460 → debit closing
        assert s.closing_balance.amount == Decimal('113460')
        assert s.closing_balance.indicator == 'D'
        assert s.opening_balance.amount == Decimal('0')


# ---------------------------------------------------------------------------
# Parser: Banco Santander style (metadata + cargo/abono)
# ---------------------------------------------------------------------------

class TestSantander:

    def setup_method(self):
        self.p = ExcelParser()
        self.r = self.p.parse('excel_santander.xlsx', read_fixture_bytes('excel_santander.xlsx'))

    def test_no_errors(self):
        assert self.r.errors == []

    def test_account_from_metadata(self):
        assert self.r.statements[0].account_id == '0-000-76-32920-6'

    def test_transaction_count(self):
        assert len(self.r.statements[0].transactions) == 4

    def test_date_parse(self):
        t = self.r.statements[0].transactions[0]
        assert t.value_date == date(2026, 8, 17)
        assert t.indicator == 'C'
        assert t.amount == Decimal('74846')

    def test_debit_cargo(self):
        t = self.r.statements[0].transactions[1]
        assert t.indicator == 'D'
        assert t.amount == Decimal('18690')

    def test_has_generator_roundtrip(self):
        mt = MT940Generator().generate(self.r)
        xml = Camt053Generator().generate(self.r)
        assert ':20:' in mt and '<?xml' in xml


# ---------------------------------------------------------------------------
# Parser: Banco de Chile style (xlsx mirror of .xls layout)
# ---------------------------------------------------------------------------

class TestChile:

    def setup_method(self):
        self.p = ExcelParser()
        self.r = self.p.parse('excel_chile.xlsx', read_fixture_bytes('excel_chile.xlsx'))

    def test_no_errors(self):
        assert self.r.errors == []

    def test_account_from_metadata(self):
        assert self.r.statements[0].account_id == '00-033-32252-17'

    def test_currency_metadata(self):
        assert self.r.statements[0].currency == 'CLP'

    def test_transaction_count(self):
        assert len(self.r.statements[0].transactions) == 3

    def test_debit(self):
        t = self.r.statements[0].transactions[0]
        assert t.value_date == date(2026, 8, 13)
        assert t.indicator == 'D'
        assert t.amount == Decimal('5699')

    def test_credit(self):
        t = self.r.statements[0].transactions[2]
        assert t.indicator == 'C'
        assert t.amount == Decimal('5000')


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:

    def test_not_a_workbook(self, parser):
        r = parser.parse('bad.xlsx', b'this is not an excel file')
        assert len(r.errors) > 0

    def test_no_header(self, parser):
        import openpyxl
        from io import BytesIO
        w = openpyxl.Workbook(); ws = w.active
        ws.append(['hola', 'mundo'])
        ws.append(['a', 'b'])
        buf = BytesIO(); w.save(buf)
        r = parser.parse('nohdr.xlsx', buf.getvalue())
        assert len(r.errors) > 0
        assert 'cabecera' in r.errors[0].lower()


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def upload_excel(client, path, target=None):
    data = {'file': (io.BytesIO(read_fixture_bytes(path)), path)}
    if target:
        data['target'] = target
    return client.post('/api/convert-excel', data=data,
                       content_type='multipart/form-data')


class TestRoutes:

    def test_parse_excel_json(self, client):
        r = client.post('/api/parse-excel',
                        data={'file': (io.BytesIO(read_fixture_bytes('excel_santander.xlsx')), 'excel_santander.xlsx')},
                        content_type='multipart/form-data')
        assert r.status_code == 200
        j = r.get_json()
        assert j['errors'] == []
        assert j['statement_count'] == 1

    def test_convert_excel_default_xml(self, client):
        r = upload_excel(client, 'excel_santander.xlsx')
        assert r.status_code == 200
        assert 'xml' in r.content_type
        assert '<?xml' in r.data.decode('utf-8')

    def test_convert_excel_mt940(self, client):
        r = upload_excel(client, 'excel_santander.xlsx', target='mt940')
        assert r.status_code == 200
        assert 'text' in r.content_type
        assert ':20:' in r.data.decode('utf-8')

    def test_parse_excel_wrong_extension(self, client):
        r = client.post('/api/parse-excel',
                        data={'file': (io.BytesIO(b'xxx'), 'file.mt940')},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_convert_excel_no_file(self, client):
        r = client.post('/api/convert-excel')
        assert r.status_code == 400

    def test_convert_excel_bad_content(self, client):
        r = client.post('/api/convert-excel',
                        data={'file': (io.BytesIO(b'not excel'), 'bad.xlsx'), 'target': 'xml'},
                        content_type='multipart/form-data')
        assert r.status_code == 422