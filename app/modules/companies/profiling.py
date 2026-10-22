"""Deterministic natural-language company profile used for embeddings and lexical context."""
from .dto import CompanyRecord

BANK_SERVICE_LABELS = {
    'cash_settlement_rko': 'расчётно-кассовое обслуживание',
    'bank_guarantees': 'банковские гарантии',
    'loans': 'кредитные продукты',
    'leasing': 'лизинг',
    'deposits': 'депозиты',
    'salary_project': 'зарплатный проект',
    'factoring': 'факторинг',
}


def _rub(value):
    return f'{value:,}'.replace(',', ' ') + ' ₽'


def _bn(value):
    return _decimal(value) + ' млрд ₽'


def _pct(value):
    return _decimal(value) + '%'


def _decimal(value):
    return f'{value:.2f}'.replace('.', ',')


def _listed(values):
    return ', '.join(values) if values else 'не указаны'


def _bank_services(record):
    return [BANK_SERVICE_LABELS[name] for name, enabled in record.main.bank_services.model_dump().items()
            if enabled and name in BANK_SERVICE_LABELS]


def _counterparty_industries(record):
    items = record.payments.top_okved[:3]
    return '; '.join(f'{item.okved_class} — {item.okved_name} ({_pct(item.share_pct)})'
                     for item in items)


def _counterparty_regions(record):
    items = record.payments.geography.top_regions[:3]
    return '; '.join(f'{item.region} ({_pct(item.share_pct)})' for item in items)


def _largest_external_counterparties(record):
    items = [item for item in record.payments.counterparties.top_3 if not item.is_intragroup][:3]
    return '; '.join(f'{item.okved_name} ({item.region}, {_pct(item.share_pct)})' for item in items)


def build_profile_text(company: CompanyRecord) -> str:
    """Build a compact profile; the most discriminative facts come first."""
    main, payments = company.main, company.payments
    totals, concentration, two_way = payments.totals, payments.counterparties, payments.two_way_links
    lines = [
        f'Компания {company.company_id}.',
        f'Основной ОКВЭД: {main.okved.code} — {main.okved.name}.',
        f'Раздел ОКВЭД: {main.okved.section.code} — {main.okved.section.name}.',
        f'Регистрация: {main.location.region}, {main.location.city}.',
        f'Форма собственности: {main.ownership_form}.',
        f'Годовая выручка: {_bn(main.annual_revenue_bn_rub)} ({_rub(main.annual_revenue_rub)}).',
        f'Стадия развития: {main.business_stage or "не указана"}.',
        f'Страны внешней торговли: {_listed(main.foreign_trade_countries)}.',
        f'Банковские услуги: {_listed(_bank_services(company))}.',
        f'Платёжный оборот: {_bn(totals.turnover_rub / 1_000_000_000)}; '
        f'контрагентов: {totals.unique_counterparties_count}; связей: {totals.edges_count}.',
        f'Концентрация: топ-1 {_pct(concentration.top_1_share_pct)}, '
        f'топ-3 {_pct(concentration.top_3_share_pct)}, HHI {_decimal(concentration.hhi)}; '
        f'внутригрупповой оборот {_pct(totals.intragroup_share_pct)}.',
        'Отрасли контрагентов: ' + (_counterparty_industries(company) or 'нет данных') + '.',
        'География контрагентов: ' + (_counterparty_regions(company) or 'нет данных') + '.',
    ]
    external = _largest_external_counterparties(company)
    if external:
        lines.append('Крупнейшие внешние контрагенты: ' + external + '.')
    lines.append(f'Двусторонние связи: {two_way.count} ({_pct(two_way.share_pct)}).')
    return '\n'.join(lines)
