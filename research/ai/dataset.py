"""Read prepared company/payment snapshots without inventing observation periods."""
import json
from pathlib import Path

from contracts import CompanyProfile
from retrieval import RetrievedSource, timestamp

SERVICES = {'cash_settlement_rko': 'РКО', 'bank_guarantees': 'Банковские гарантии',
            'loans': 'Кредиты', 'leasing': 'Лизинг', 'deposits': 'Депозиты',
            'salary_project': 'Зарплатный проект', 'factoring': 'Факторинг'}
LIMITATION = ('Агрегаты платежей за неизвестный период. Дат платежей нет; '
              'динамика и сезонность неизвестны. География отражает регистрацию '
              'контрагентов, а не место операций; оборот не равен выручке. '
              'Роли покупателя/поставщика и причинная связь с новостью не установлены.')


def payment_sources(company_id, payments, *, available_at, locator_prefix):
    return [RetrievedSource(source_id=f'metric:{company_id}:{section}', kind='metric',
        company_id=company_id, title=f'Агрегаты платежей: {section}',
        text=LIMITATION + '\n' + json.dumps({section: payments[section]}, ensure_ascii=False),
        published_at=timestamp(available_at).isoformat(),
        locator=f'{locator_prefix}/payments/{section}')
        for section in ('totals', 'counterparties', 'top_okved', 'geography', 'two_way_links')]


class CompanyDataset:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        self.available_at = timestamp(self.data['meta']['generated_at_utc'])
        self.rows, self.groups = {}, {}
        for group in self.data['groups']:
            self.groups[group['group_id']] = group
            for row in group['companies']:
                if row['company_id'] in self.rows:
                    raise ValueError('Duplicate company identity')
                self.rows[row['company_id']] = row

    def profile(self, company_id):
        row = self.rows[company_id]
        main = row['main']
        return CompanyProfile(id=company_id, provenance='dataset',
            source_ref='docs/companies/companies_analytics.json#' + company_id,
            okved_codes=[main['okved']['code']], okved_names=[main['okved']['name']],
            registration_region=main['location']['region'], ownership_form=main['ownership_form'],
            annual_revenue_rub=float(main['annual_revenue_rub']),
            banking_services=[SERVICES[key] for key, value in main['bank_services'].items() if value is True],
            trade_countries=main['foreign_trade_countries'] or None, development_stage=main['business_stage'])

    def metrics(self, company_id, *, as_of):
        if self.available_at > timestamp(as_of):
            return []
        payments = self.rows[company_id]['payments']
        return payment_sources(company_id, payments, available_at=self.available_at,
                               locator_prefix=f'docs/companies/companies_analytics.json#{company_id}')

    def query(self, company_id, *, payments=False):
        row = self.rows[company_id]
        main = row['main']
        query = main['okved']['name'] + '. ' + main['location']['region'] + '.'
        if payments:
            query += ' Связанные отрасли контрагентов: ' + '; '.join(
                item['okved_name'] for item in row['payments']['top_okved']) + '.'
        return query


class DatasetRepository:
    """Expose the existing agent interface over a dataset snapshot and shared news DB."""
    def __init__(self, dataset, news_reader, bank_reader=None):
        self.dataset, self.news_reader, self.bank_reader = dataset, news_reader, bank_reader

    def resolve_news_id(self, news_id, *, as_of):
        return self.news_reader.resolve(news_id, as_of=as_of)

    def get_company_profile(self, company_id):
        return self.dataset.profile(company_id)

    def get_news(self, news_id, *, as_of):
        return self.news_reader.get_news(news_id, as_of=as_of)

    def news_metadata(self, news_id):
        return self.news_reader.metadata.get(news_id, {})

    def get_company_metrics(self, company_id, *, as_of):
        return self.dataset.metrics(company_id, as_of=as_of)

    def search_news(self, query, *, as_of, exclude_id, limit=3):
        return self.news_reader.search_news(query, as_of=as_of, exclude_id=exclude_id, limit=limit)

    def search_bank_analytics(self, query, *, as_of, limit=3):
        if self.bank_reader is None:
            from database import DatabaseError
            raise DatabaseError('Bank documents not loaded')
        return self.bank_reader.search(query, as_of=as_of, limit=limit)
