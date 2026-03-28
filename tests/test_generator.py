"""Tests for the camt.053 XML generator."""
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest

from app.converter import Camt053Generator
from app.parser import MT940Parser
from app.parser.models import Balance, ParseResult, Statement, Transaction

NS = 'urn:iso:std:iso:20022:tech:xsd:camt.053.001.08'


def q(tag: str) -> str:
    return f'{{{NS}}}{tag}'


def make_minimal_result() -> ParseResult:
    stmt = Statement(
        transaction_reference='TEST-REF-001',
        related_reference='NONREF',
        account_id='DE89370400440532013000',
        iban='DE89370400440532013000',
        bic='COBADEFFXXX',
        currency='EUR',
        statement_number='00001',
        sequence_number='001',
        opening_balance=Balance('C', date(2024, 1, 1), 'EUR', Decimal('1000.00'), 'OPBD'),
        closing_balance=Balance('C', date(2024, 1, 31), 'EUR', Decimal('1500.00'), 'CLBD'),
        available_balance=None,
        transactions=[
            Transaction(
                value_date=date(2024, 1, 15),
                booking_date=date(2024, 1, 15),
                indicator='C',
                amount=Decimal('500.00'),
                transaction_type_id='NTRF',
                customer_reference='CUST-001',
                bank_reference='BANK-001',
                narrative='Pago cliente ABC',
                sequence_number=0,
            ),
            Transaction(
                value_date=date(2024, 1, 20),
                booking_date=date(2024, 1, 20),
                indicator='D',
                amount=Decimal('50.00'),
                transaction_type_id='NCHK',
                customer_reference='CUST-002',
                bank_reference=None,
                narrative=None,
                sequence_number=1,
            ),
        ],
    )
    return ParseResult(statements=[stmt], raw_text='', filename='test.mt940')


class TestGeneratorStructure:
    def setup_method(self):
        self.gen = Camt053Generator()
        self.result = make_minimal_result()
        xml_str = self.gen.generate(self.result)
        self.root = ET.fromstring(xml_str.encode('utf-8') if xml_str.startswith('<?xml') else xml_str)

    def test_root_element(self):
        assert self.root.tag == q('Document')

    def test_bk_to_cstmr_stmt(self):
        bks = self.root.find(q('BkToCstmrStmt'))
        assert bks is not None

    def test_group_header(self):
        grp = self.root.find(f'.//{q("GrpHdr")}')
        assert grp is not None
        msg_id = grp.find(q('MsgId'))
        assert msg_id is not None
        assert len(msg_id.text) > 0
        cre_dt = grp.find(q('CreDtTm'))
        assert cre_dt is not None

    def test_statement_id(self):
        stmt_id = self.root.find(f'.//{q("Stmt")}/{q("Id")}')
        assert stmt_id is not None
        assert stmt_id.text == 'TEST-REF-001'

    def test_account_iban(self):
        iban = self.root.find(f'.//{q("Acct")}/{q("Id")}/{q("IBAN")}')
        assert iban is not None
        assert iban.text == 'DE89370400440532013000'

    def test_account_bic(self):
        bic = self.root.find(f'.//{q("Acct")}/{q("Svcr")}/{q("FinInstnId")}/{q("BICFI")}')
        assert bic is not None
        assert bic.text == 'COBADEFFXXX'

    def test_account_currency(self):
        ccy = self.root.find(f'.//{q("Acct")}/{q("Ccy")}')
        assert ccy is not None
        assert ccy.text == 'EUR'

    def test_balances_present(self):
        bals = self.root.findall(f'.//{q("Bal")}')
        assert len(bals) == 2  # opening + closing

    def test_opening_balance(self):
        bals = self.root.findall(f'.//{q("Bal")}')
        opbd = next(
            (b for b in bals if b.find(f'.//{q("Cd")}') is not None and b.find(f'.//{q("Cd")}').text == 'OPBD'),
            None,
        )
        assert opbd is not None
        amt = opbd.find(q('Amt'))
        assert amt is not None
        assert amt.text == '1000.00'
        assert amt.get('Ccy') == 'EUR'
        assert opbd.find(q('CdtDbtInd')).text == 'CRDT'

    def test_entries_count(self):
        entries = self.root.findall(f'.//{q("Ntry")}')
        assert len(entries) == 2

    def test_credit_entry(self):
        entries = self.root.findall(f'.//{q("Ntry")}')
        credit = next(
            (e for e in entries if e.find(q('CdtDbtInd')) is not None and e.find(q('CdtDbtInd')).text == 'CRDT'),
            None,
        )
        assert credit is not None
        amt = credit.find(q('Amt'))
        assert amt.text == '500.00'
        assert amt.get('Ccy') == 'EUR'

    def test_debit_entry(self):
        entries = self.root.findall(f'.//{q("Ntry")}')
        debit = next(
            (e for e in entries if e.find(q('CdtDbtInd')) is not None and e.find(q('CdtDbtInd')).text == 'DBIT'),
            None,
        )
        assert debit is not None
        assert debit.find(q('Amt')).text == '50.00'

    def test_entry_status_booked(self):
        for entry in self.root.findall(f'.//{q("Ntry")}'):
            sts = entry.find(f'.//{q("Sts")}/{q("Cd")}')
            assert sts is not None
            assert sts.text == 'BOOK'

    def test_entry_remittance_info(self):
        ustrd = self.root.find(f'.//{q("Ustrd")}')
        assert ustrd is not None
        assert ustrd.text == 'Pago cliente ABC'

    def test_bank_tx_code(self):
        codes = self.root.findall(f'.//{q("BkTxCd")}/{q("Prtry")}/{q("Cd")}')
        assert len(codes) == 2
        assert codes[0].text == 'NTRF'
        assert codes[1].text == 'NCHK'


class TestGeneratorFromParser:
    """Integration test: parser → generator → valid XML."""

    SAMPLE = (
        ':20:INTEG-TEST\n:21:NONREF\n:25:ES7921000813610123456789/CAIXESBB\n:28C:1/1\n'
        ':60F:C240101EUR10000,00\n'
        ':61:2401150115C2500,00NTRFREF-100000000//BREF-ABC\n:86:Ingreso test\n'
        ':62F:C240115EUR12500,00\n-\n'
    )

    def test_full_roundtrip(self):
        parser = MT940Parser()
        gen = Camt053Generator()
        result = parser.parse(self.SAMPLE, 'integ.mt940')
        assert result.errors == []
        xml_str = gen.generate(result)
        assert '<?xml' in xml_str
        assert 'camt.053.001.08' in xml_str
        root = ET.fromstring(xml_str.encode('utf-8') if xml_str.startswith('<?xml') else xml_str)
        assert root.tag == q('Document')
        entries = root.findall(f'.//{q("Ntry")}')
        assert len(entries) == 1
        assert entries[0].find(q('CdtDbtInd')).text == 'CRDT'
