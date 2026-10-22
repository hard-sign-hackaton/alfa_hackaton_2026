from datetime import datetime, timezone

from sqlalchemy import select, text as sql
from sqlalchemy.dialects.postgresql import insert

from .dto import CompanyGroup, CompanyRecord, EmbeddingInput, NormalizedCompany
from .models import Company, CompanyEmbedding, CompanyEmbeddingProfile, CompanyGroup as GroupRow, CompanyImportRun


class CompanyRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def save_group(self, group: CompanyGroup):
        values = dict(
            id=group.group_id,
            rank=group.selection.rank,
            okved_section_code=group.selection.okved_section.code,
            okved_section_name=group.selection.okved_section.name,
            okved_class=group.selection.okved_class,
            main_okved_code=group.selection.main_okved.code,
            main_okved_name=group.selection.main_okved.name,
            headquarters_region=group.selection.headquarters_region,
            headquarters_city=group.selection.headquarters_city,
            edges_count=group.selection.group_edges_count,
            min_company_edges_count=group.selection.min_company_edges_count,
            companies_count=group.summary.composition.companies_count,
            total_revenue_rub=group.summary.composition.total_revenue_rub,
            reason=group.selection.reason,
            details=group.model_dump(mode='json'),
        )
        with self.session.begin() as session:
            old = session.get(GroupRow, group.group_id)
            outcome = 'inserted' if old is None else 'updated'
            statement = insert(GroupRow).values(**values)
            session.execute(statement.on_conflict_do_update(
                index_elements=['id'], set_={key: value for key, value in values.items() if key != 'id'}))
        return outcome

    def save_company(self, company: NormalizedCompany):
        record = company.record
        main = record.main
        values = dict(
            id=record.company_id,
            group_id=main.group_id,
            okved_code=main.okved.code,
            okved_name=main.okved.name,
            okved_section_code=main.okved.section.code,
            okved_section_name=main.okved.section.name,
            city=main.location.city,
            region=main.location.region,
            ownership_form=main.ownership_form,
            annual_revenue_rub=main.annual_revenue_rub,
            business_stage=main.business_stage,
            client_type=main.client_type,
            bank_services=main.bank_services.model_dump(mode='json'),
            foreign_trade_countries=main.foreign_trade_countries,
            profile_text=company.profile_text,
            content_hash=company.content_hash,
            details=record.model_dump(mode='json'),
            imported_at=datetime.now(timezone.utc),
        )
        with self.session.begin() as session:
            # Serialize imports of the same company across CLI processes.
            session.execute(sql('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                            {'key': record.company_id})
            old = session.get(Company, record.company_id)
            if old is not None and old.details == values['details']:
                # Re-importing the same snapshot must not move its availability date.
                values['imported_at'] = old.imported_at
            outcome = ('inserted' if old is None else
                       'updated' if old.content_hash != company.content_hash else 'unchanged')
            statement = insert(Company).values(**values)
            session.execute(statement.on_conflict_do_update(
                index_elements=['id'], set_={key: value for key, value in values.items() if key != 'id'}))
        return outcome

    def record_run(self, report):
        with self.session.begin() as session:
            session.add(CompanyImportRun(
                started_at=datetime.fromisoformat(report['started_at']),
                finished_at=datetime.fromisoformat(report['finished_at']),
                status=report['status'],
                report=report,
            ))

    def list_companies(self):
        with self.session() as session:
            rows = session.scalars(select(Company).order_by(Company.id))
            return [CompanyRecord.model_validate(row.details) for row in rows]

    def get_company(self, company_id):
        with self.session() as session:
            row = session.get(Company, company_id)
            return CompanyRecord.model_validate(row.details) if row else None


class CompanyEmbeddingRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def ensure_profile(self, profile):
        with self.session.begin() as session:
            session.execute(insert(CompanyEmbeddingProfile).values(**profile)
                            .on_conflict_do_nothing(index_elements=['id']))

    def pending(self, profile_id, limit):
        with self.session() as session:
            query = select(Company).outerjoin(
                CompanyEmbedding,
                (CompanyEmbedding.company_id == Company.id) & (CompanyEmbedding.profile_id == profile_id))
            query = query.where(
                (CompanyEmbedding.id.is_(None)) | (CompanyEmbedding.input_hash != Company.content_hash)
            ).order_by(Company.id).limit(limit)
            return [EmbeddingInput(company.id, company.profile_text, company.content_hash)
                    for company in session.scalars(query)]

    def save_embedding(self, company, profile_id, vector, token_count, truncated):
        with self.session.begin() as session:
            current = session.scalar(select(Company).where(Company.id == company.company_id).with_for_update())
            if current is None or current.content_hash != company.content_hash:
                return False
            statement = insert(CompanyEmbedding).values(
                company_id=company.company_id,
                profile_id=profile_id,
                input_hash=company.content_hash,
                token_count=token_count,
                truncated=truncated,
                vector=vector,
                created_at=datetime.now(timezone.utc),
            )
            session.execute(statement.on_conflict_do_update(
                index_elements=['company_id', 'profile_id'],
                set_={key: getattr(statement.excluded, key)
                      for key in ('input_hash', 'token_count', 'truncated', 'vector', 'created_at')}))
            return True

    def search_pg(self, vector, profile_id, top_k, *, as_of=None):
        if not 1 <= top_k <= 100:
            raise ValueError('top-k must be between 1 and 100')
        cutoff = as_of or datetime.now(timezone.utc)
        if cutoff.tzinfo is None:
            raise ValueError('Search time requires a timezone')
        distance = CompanyEmbedding.vector.cosine_distance(vector)
        with self.session() as session:
            session.execute(sql("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            session.execute(sql('SET LOCAL hnsw.ef_search = 64'))
            statement = select(
                Company.id,
                Company.group_id,
                Company.okved_code,
                Company.okved_name,
                Company.city,
                Company.region,
                Company.annual_revenue_rub,
                Company.profile_text,
                (1 - distance).label('similarity'),
            ).select_from(CompanyEmbedding).join(
                Company, Company.id == CompanyEmbedding.company_id).where(
                    CompanyEmbedding.profile_id == profile_id,
                    CompanyEmbedding.input_hash == Company.content_hash,
                    Company.imported_at <= cutoff)
            rows = session.execute(statement.order_by(distance, Company.id).limit(top_k)).all()
        return [hit(row) for row in rows]

    def list_profiles(self):
        with self.session() as session:
            return [self._profile(row) for row in session.scalars(
                select(CompanyEmbeddingProfile).order_by(CompanyEmbeddingProfile.id))]

    @staticmethod
    def _profile(row):
        return {key: getattr(row, key) for key in
                ('id', 'model', 'revision', 'dimensions', 'normalized', 'preparation')}


def hit(row):
    result = dict(row._mapping)
    if result.get('annual_revenue_rub') is not None:
        result['annual_revenue_rub'] = int(result['annual_revenue_rub'])
    if 'similarity' in result:
        result['similarity'] = float(result['similarity'])
    return result
