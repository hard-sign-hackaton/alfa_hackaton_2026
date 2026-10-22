import unittest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from brief import BriefSelection, CompactResult, fallback_brief, resolve_brief
from contracts import Claim, Evidence, Insight, evidence_sources
from fixtures import profiles, news
from langchain_provider import LangChainClient
from model_config import GatewaySettings
from tasks import NewsPreparation, TopicClassification, EventExtraction


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.company, self.news = profiles()[0], news()[0]
        company_source = 'company:'+self.company.id+':okved_codes'
        self.news_evidence = Evidence(source_id='news:'+self.news.id, quote=self.news.title)
        company_evidence = Evidence(source_id=company_source, quote=evidence_sources(self.company,self.news)[company_source])
        self.insight = Insight(company_id=self.company.id, news_id=self.news.id, status='supported', summary='Fixture',
            claims=[Claim(kind='fact',text=self.news.title,evidence=[self.news_evidence]),
                Claim(kind='fact',text='Company activity.',evidence=[company_evidence]),
                Claim(kind='hypothesis',text='Conditional impact.',evidence=[self.news_evidence,company_evidence])],
            missing_data=[],follow_up_answer=None)
        self.prepared = NewsPreparation(classification=TopicClassification(news_id=self.news.id, business_relevant=True,
            topics=['metallurgy'], evidence=[self.news_evidence]),
            extraction=EventExtraction(news_id=self.news.id, facts=[self.insight.claims[0]],missing_data=[]))
        self.selection = BriefSelection.model_validate(dict(news_summary=dict(text='News event.',claim_ids=[0]),
            short_answer=dict(text='Conditional company effect.',claim_ids=[2]),
            importance=dict(level='medium',reason=dict(text='Indirect exposure.',claim_ids=[0,1]))))

    def resolve(self, selection=None, insight=None):
        return resolve_brief(selection or self.selection, insight or self.insight, self.company,self.news,self.prepared,[])

    def test_public_output_is_short_classified_and_cites_server_owned_claims(self):
        result = self.resolve()
        self.assertEqual(result.classification.topics,['metallurgy'])
        self.assertEqual(result.classification.importance,'medium')
        self.assertEqual(result.classification.importance_method,'classifier')
        self.assertEqual(result.evidence.news_summary,[self.news_evidence])
        self.assertIsInstance(CompactResult.model_validate(result.model_dump()),CompactResult)

    def test_unknown_claim_and_hypothesis_as_news_fact_are_rejected(self):
        for ids in ([999],[2]):
            changed = self.selection.model_copy(deep=True)
            changed.news_summary.claim_ids = ids
            with self.assertRaises(ValueError): self.resolve(changed)

    def test_importance_requires_company_premises_and_cannot_be_high_when_insufficient(self):
        changed = self.selection.model_copy(deep=True)
        changed.importance.reason.claim_ids = [0]
        with self.assertRaises(ValueError): self.resolve(changed)
        changed = self.selection.model_copy(deep=True); changed.importance.level='high'
        uncertain = self.insight.model_copy(update=dict(status='insufficient_data',missing_data=['Exposure']))
        with self.assertRaises(ValueError): self.resolve(changed,uncertain)

    def test_unavailable_model_does_not_invent_importance(self):
        result = fallback_brief(self.insight,self.company,self.news,self.prepared)
        self.assertIsNone(result.classification.importance)
        self.assertEqual(result.status,'partial')

    def test_brief_routes_to_gemma_and_resolves_citations(self):
        routes=[]
        def factory(route):
            routes.append(route)
            return RunnableLambda(lambda prompt: AIMessage(content=self.selection.model_dump_json()))
        client=LangChainClient(settings=GatewaySettings.from_env({}),model_factory=factory)
        result=client.brief(self.company,self.news,self.insight,self.prepared)
        self.assertEqual(result.status,'ready')
        self.assertEqual(routes[0].task,'brief')
        self.assertIn('gemma',routes[0].model)


if __name__=='__main__': unittest.main()
