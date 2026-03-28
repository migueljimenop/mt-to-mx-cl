from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional


@dataclass
class Balance:
    """Represents a balance field (:60F:, :60M:, :62F:, :62M:, :64:, :65:)."""
    indicator: str       # 'C' (credit) or 'D' (debit)
    date: date
    currency: str        # ISO 4217, e.g. 'EUR'
    amount: Decimal
    balance_type: str    # 'OPBD', 'CLBD', 'FWAV', 'ITBD'

    def to_dict(self) -> dict:
        return {
            'indicator': self.indicator,
            'date': self.date.isoformat(),
            'currency': self.currency,
            'amount': str(self.amount),
            'balance_type': self.balance_type,
        }


@dataclass
class Transaction:
    """Represents a single statement line (:61:) with optional narrative (:86:)."""
    value_date: date
    booking_date: Optional[date]
    indicator: str               # 'C', 'D', 'RC' (reversal credit), 'RD'
    amount: Decimal
    transaction_type_id: str     # SWIFT transaction type code, e.g. 'NTRF'
    customer_reference: str
    bank_reference: Optional[str]
    narrative: Optional[str]     # From :86: field
    sequence_number: int         # 0-based position within the statement

    def to_dict(self) -> dict:
        return {
            'value_date': self.value_date.isoformat(),
            'booking_date': self.booking_date.isoformat() if self.booking_date else None,
            'indicator': self.indicator,
            'amount': str(self.amount),
            'transaction_type_id': self.transaction_type_id,
            'customer_reference': self.customer_reference,
            'bank_reference': self.bank_reference,
            'narrative': self.narrative,
            'sequence_number': self.sequence_number,
        }


@dataclass
class Statement:
    """Represents one MT940 statement block."""
    transaction_reference: str        # :20:
    related_reference: Optional[str]  # :21:
    account_id: str                   # :25: raw value
    iban: Optional[str]               # Parsed IBAN from :25:
    bic: Optional[str]                # BIC from :25:
    currency: Optional[str]           # Derived from balances or :25:
    statement_number: str             # :28C: left of /
    sequence_number: str              # :28C: right of /
    opening_balance: Optional[Balance]
    closing_balance: Optional[Balance]
    available_balance: Optional[Balance]
    transactions: List[Transaction] = field(default_factory=list)
    parse_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'transaction_reference': self.transaction_reference,
            'related_reference': self.related_reference,
            'account_id': self.account_id,
            'iban': self.iban,
            'bic': self.bic,
            'currency': self.currency,
            'statement_number': self.statement_number,
            'sequence_number': self.sequence_number,
            'opening_balance': self.opening_balance.to_dict() if self.opening_balance else None,
            'closing_balance': self.closing_balance.to_dict() if self.closing_balance else None,
            'available_balance': self.available_balance.to_dict() if self.available_balance else None,
            'transactions': [t.to_dict() for t in self.transactions],
            'parse_warnings': self.parse_warnings,
        }


@dataclass
class ParseResult:
    """Top-level result of parsing an MT940 file."""
    statements: List[Statement]
    raw_text: str
    filename: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'filename': self.filename,
            'statement_count': len(self.statements),
            'statements': [s.to_dict() for s in self.statements],
            'errors': self.errors,
            'warnings': self.warnings,
        }
