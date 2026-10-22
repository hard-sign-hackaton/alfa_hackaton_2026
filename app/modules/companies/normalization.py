"""Validate the documented dataset and attach deterministic embedding input."""
from dataclasses import dataclass
from typing import Any

from .dto import CompaniesDataset, CompanyGroup, CompanyRecord, NormalizedCompany
from .identity import text_hash
from .profiling import build_profile_text


@dataclass(frozen=True)
class NormalizedDataset:
    dataset: CompaniesDataset
    companies: tuple[NormalizedCompany, ...]

    @property
    def groups(self):
        return self.dataset.groups


def normalize_dataset(raw: dict[str, Any]) -> NormalizedDataset:
    dataset = CompaniesDataset.model_validate(raw)
    if not dataset.groups:
        raise ValueError('Dataset contains no groups')
    group_ids: set[str] = set()
    company_ids: set[str] = set()
    companies: list[NormalizedCompany] = []
    for group in dataset.groups:
        _validate_group(group, group_ids)
        for record in group.companies:
            _validate_company(record, group, company_ids)
            profile_text = build_profile_text(record)
            if not profile_text.strip():
                raise ValueError(f'Company {record.company_id} produced an empty profile')
            companies.append(NormalizedCompany(record=record, profile_text=profile_text,
                                               content_hash=text_hash(profile_text)))
    if not companies:
        raise ValueError('Dataset contains no companies')
    return NormalizedDataset(dataset=dataset, companies=tuple(companies))


def _validate_group(group: CompanyGroup, seen: set[str]):
    if group.group_id in seen:
        raise ValueError(f'Duplicate group_id: {group.group_id}')
    seen.add(group.group_id)
    expected = group.summary.composition.companies_count
    if expected != len(group.companies):
        raise ValueError(f'Group {group.group_id} declares {expected} companies but contains {len(group.companies)}')
    sections = {item.code for item in group.summary.composition.okved_sections}
    if sections and group.selection.okved_section.code not in sections:
        raise ValueError(f'Group {group.group_id} has inconsistent OKVED section data')


def _validate_company(record: CompanyRecord, group: CompanyGroup, seen: set[str]):
    if record.company_id in seen:
        raise ValueError(f'Duplicate company_id: {record.company_id}')
    seen.add(record.company_id)
    if record.main.group_id != group.group_id:
        raise ValueError(f'Company {record.company_id} does not belong to group {group.group_id}')
