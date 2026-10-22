"""Company-scoped read tools and their server-owned evidence registry."""
import json

from langchain_core.tools import StructuredTool
from pydantic import Field

from contracts import StrictModel
from retrieval import source_registry


class NoArguments(StrictModel):
    pass


class SearchArguments(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=3, ge=1, le=3)


class ToolSession:
    MAX_SOURCES = 8
    MAX_SOURCE_CHARACTERS = 24000

    def __init__(self, repository, company, news, *, as_of):
        self.repository, self.company, self.news, self.as_of = repository, company, news, as_of
        self.sources = {}
        self.trace = []
        self._cache = {}
        self._unavailable_tools = set()
        self.tools = [
            StructuredTool.from_function(self.profile, name='get_company_profile', args_schema=NoArguments,
                                         description='Read the selected company profile. Cannot select another company.'),
            StructuredTool.from_function(self.metrics, name='get_company_metrics', args_schema=NoArguments,
                                         description='Read available prepared metrics for the selected company before as_of. No raw transactions.'),
            StructuredTool.from_function(self.news_search, name='search_news', args_schema=SearchArguments,
                                         description='Search other published news in PostgreSQL by Russian search words. Empty results are not evidence.'),
            StructuredTool.from_function(self.bank_search, name='search_bank_analytics', args_schema=SearchArguments,
                                         description='Search stored bank/sector analytics by Russian search words. Use excerpts as attributed sources.'),
        ]

    def _collect(self, values):
        checked = source_registry(values, self.company, self.news, as_of=self.as_of)
        included, limited = [], False
        for source_id, value in checked.items():
            if source_id in self.sources:
                if self.sources[source_id] != value:
                    raise ValueError('Source changed during retrieval')
            elif (len(self.sources) >= self.MAX_SOURCES or
                  sum(len(source.text) for source in self.sources.values()) + len(value.text) > self.MAX_SOURCE_CHARACTERS):
                limited = True
                continue
            else:
                self.sources[source_id] = value
            included.append(value.model_dump())
        return {'status': 'limited' if limited else ('found' if included else 'not_found'), 'sources': included,
                'note': 'Only returned excerpts may be cited. Missing rows do not prove absence of exposure.'}

    def profile(self):
        return {'status': 'found', 'company': self.company.model_dump()}

    def metrics(self):
        values = self.repository.get_company_metrics(self.company.id, as_of=self.as_of)
        priority = {'top_okved': 0, 'counterparties': 1, 'totals': 2}
        values = sorted(values, key=lambda value: priority.get(value.source_id.rsplit(':', 1)[-1], 3))
        result = self._collect(values[:3])
        if len(values) > 3:
            result['note'] += ' Returned three selected metric sources; other aggregates were not included in context.'
        return result

    def news_search(self, query, limit=3):
        return self._collect(self.repository.search_news(query, as_of=self.as_of, exclude_id=self.news.id, limit=limit))

    def bank_search(self, query, limit=3):
        return self._collect(self.repository.search_bank_analytics(query, as_of=self.as_of, limit=limit))

    def invoke(self, name, args):
        from database import DatabaseError
        key = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        cached = key in self._cache or name in self._unavailable_tools
        if cached:
            result = self._cache.get(key, {'status': 'unavailable', 'reason': 'Source unavailable during this run; no repeated database request'})
        else:
            tool = next((tool for tool in self.tools if tool.name == name), None)
            if tool is None:
                result = {'status': 'rejected', 'reason': 'Unknown tool'}
            else:
                try:
                    validated = tool.args_schema.model_validate(args)
                    result = tool.invoke(validated.model_dump())
                except DatabaseError:
                    result = {'status': 'unavailable', 'reason': 'Database read failed'}
                    self._unavailable_tools.add(name)
                except (ValueError, TypeError):
                    result = {'status': 'rejected', 'reason': 'Invalid arguments or retrieved source'}
            self._cache[key] = result
        self.trace.append({'tool': name, 'arguments': args, 'status': result['status'], 'cached': cached,
                           'source_ids': [source['source_id'] for source in result.get('sources', [])]})
        return result
