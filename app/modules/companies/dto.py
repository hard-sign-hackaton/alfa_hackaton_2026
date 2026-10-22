"""Validated company dataset models and detached exchange objects."""
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetModel(BaseModel):
    """Reject unexpected fields so changes to the documented dataset are visible."""
    model_config = ConfigDict(extra='forbid')


class OkvedSection(DatasetModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Okved(DatasetModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    section: OkvedSection


class BankServices(DatasetModel):
    cash_settlement_rko: bool | None = None
    bank_guarantees: bool | None = None
    loans: bool | None = None
    leasing: bool | None = None
    deposits: bool | None = None
    salary_project: bool | None = None
    factoring: bool | None = None


class Location(DatasetModel):
    city: str = Field(min_length=1)
    region: str = Field(min_length=1)


class CompanyMain(DatasetModel):
    okved: Okved
    bank_services: BankServices
    location: Location
    ownership_form: str = Field(min_length=1)
    annual_revenue_rub: int = Field(ge=0)
    annual_revenue_bn_rub: float = Field(ge=0)
    foreign_trade_countries: list[str] = Field(default_factory=list)
    business_stage: str | None = None
    client_type: str = Field(min_length=1)
    group_id: str = Field(min_length=1)


class PaymentTotals(DatasetModel):
    incoming_amount_rub: int = Field(ge=0)
    outgoing_amount_rub: int = Field(ge=0)
    turnover_rub: int = Field(ge=0)
    incoming_payments_count: int = Field(ge=0)
    outgoing_payments_count: int = Field(ge=0)
    edges_count: int = Field(ge=0)
    unique_counterparties_count: int = Field(ge=0)
    external_counterparties_count: int = Field(ge=0)
    intragroup_counterparties_count: int = Field(ge=0)
    intragroup_amount_rub: int = Field(ge=0)
    intragroup_share_pct: float = Field(ge=0, le=100)
    average_edge_amount_rub: int = Field(ge=0)


class TopCounterparty(DatasetModel):
    company_id: str = Field(min_length=1)
    okved_code: str = Field(min_length=1)
    okved_name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    city: str = Field(min_length=1)
    is_intragroup: bool
    incoming_amount_rub: int = Field(ge=0)
    outgoing_amount_rub: int = Field(ge=0)
    turnover_rub: int = Field(ge=0)
    payments_count: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class Counterparties(DatasetModel):
    unique_count: int = Field(ge=0)
    top_1_share_pct: float = Field(ge=0, le=100)
    top_3_share_pct: float = Field(ge=0, le=100)
    hhi: float = Field(ge=0, le=10_000)
    top_3: list[TopCounterparty] = Field(default_factory=list)


class TopOkvedCode(DatasetModel):
    okved_code: str = Field(min_length=1)
    okved_name: str = Field(min_length=1)
    counterparties_count: int = Field(ge=0)
    amount_rub: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class TopOkvedClass(DatasetModel):
    okved_class: str = Field(min_length=1)
    okved_name: str = Field(min_length=1)
    counterparties_count: int = Field(ge=0)
    amount_rub: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)
    top_codes: list[TopOkvedCode] = Field(default_factory=list)


class RegionShare(DatasetModel):
    region: str = Field(min_length=1)
    counterparties_count: int = Field(ge=0)
    amount_rub: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class CityShare(DatasetModel):
    city: str = Field(min_length=1)
    counterparties_count: int = Field(ge=0)
    amount_rub: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class PaymentGeography(DatasetModel):
    top_regions: list[RegionShare] = Field(default_factory=list)
    top_cities: list[CityShare] = Field(default_factory=list)


class TwoWayCounterparty(DatasetModel):
    company_id: str = Field(min_length=1)
    okved_code: str = Field(min_length=1)
    okved_name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    incoming_amount_rub: int = Field(ge=0)
    outgoing_amount_rub: int = Field(ge=0)
    turnover_rub: int = Field(ge=0)


class TwoWayLinks(DatasetModel):
    count: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)
    top_3: list[TwoWayCounterparty] = Field(default_factory=list)


class CompanyPayments(DatasetModel):
    totals: PaymentTotals
    counterparties: Counterparties
    top_okved: list[TopOkvedClass] = Field(default_factory=list)
    geography: PaymentGeography
    two_way_links: TwoWayLinks


class CompanyRecord(DatasetModel):
    company_id: str = Field(min_length=1)
    main: CompanyMain
    payments: CompanyPayments


class GroupOkvedCount(DatasetModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    companies_count: int = Field(ge=0)


class GroupComposition(DatasetModel):
    companies_count: int = Field(ge=1)
    total_revenue_rub: int = Field(ge=0)
    total_revenue_bn_rub: float = Field(ge=0)
    regions: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    okved_sections: list[GroupOkvedCount] = Field(default_factory=list)
    okved_classes: list[GroupOkvedCount] = Field(default_factory=list)


class GroupTransactions(DatasetModel):
    edges_count: int = Field(ge=0)
    turnover_rub: int = Field(ge=0)
    payments_count: int = Field(ge=0)
    unique_counterparties_count: int = Field(ge=0)
    external_counterparties_count: int = Field(ge=0)
    intragroup_counterparties_count: int = Field(ge=0)
    intragroup_amount_rub: int = Field(ge=0)
    intragroup_share_pct: float = Field(ge=0, le=100)


class GroupSummary(DatasetModel):
    composition: GroupComposition
    transactions: GroupTransactions


class GroupSelection(DatasetModel):
    rank: int = Field(ge=1)
    okved_section: OkvedSection
    okved_class: str = Field(min_length=1)
    main_okved: OkvedSection
    headquarters_region: str = Field(min_length=1)
    headquarters_city: str = Field(min_length=1)
    group_edges_count: int = Field(ge=0)
    min_company_edges_count: int = Field(ge=0)
    reason: str = Field(min_length=1)


class CompanyGroup(DatasetModel):
    group_id: str = Field(min_length=1)
    selection: GroupSelection
    summary: GroupSummary
    companies: list[CompanyRecord] = Field(default_factory=list)


class CompaniesDataset(DatasetModel):
    meta: dict[str, Any] = Field(default_factory=dict)
    groups: list[CompanyGroup] = Field(default_factory=list)


@dataclass(frozen=True)
class NormalizedCompany:
    """Detached company with the exact text that is embedded and stored."""
    record: CompanyRecord
    profile_text: str
    content_hash: str

    @property
    def company_id(self):
        return self.record.company_id


@dataclass(frozen=True)
class EmbeddingInput:
    company_id: str
    profile_text: str
    content_hash: str
