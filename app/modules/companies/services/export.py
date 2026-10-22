"""Export normalized companies or the research AI CompanyProfile shape."""
class CompanyExportService:
    # Canonical names used by research/ai fixtures and prompts.
    SERVICE_CODES = {
        'cash_settlement_rko': 'cash_register',
        'bank_guarantees': 'bank_guarantees',
        'loans': 'credit',
        'leasing': 'leasing',
        'deposits': 'deposit',
        'salary_project': 'payroll',
        'factoring': 'factoring',
    }

    def __init__(self, repository):
        self.repository = repository

    def export(self, ai=False):
        return [self.ai_profile(company) if ai else company.model_dump(mode='json')
                for company in self.repository.list_companies()]

    @classmethod
    def ai_profile(cls, company):
        main = company.main
        services = [cls.SERVICE_CODES.get(name, name) for name, enabled
                    in main.bank_services.model_dump().items() if enabled]
        return dict(
            id=company.company_id,
            provenance='dataset',
            source_ref=f'docs/companies/companies_analytics.json#{company.company_id}',
            okved_codes=[main.okved.code],
            okved_names=[main.okved.name],
            registration_region=main.location.region,
            ownership_form=main.ownership_form,
            annual_revenue_rub=float(main.annual_revenue_rub),
            banking_services=services,
            trade_countries=main.foreign_trade_countries or None,
            development_stage=main.business_stage,
        )
