import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.shared.embeddings.e5 import E5Provider


class E5CacheTests(unittest.TestCase):
    def model(self):
        result = Mock()
        result.get_sentence_embedding_dimension.return_value = 384
        return result

    def test_pinned_cached_model_does_not_require_network(self):
        factory, api = Mock(return_value=self.model()), Mock()
        with patch.dict(sys.modules, {'sentence_transformers': SimpleNamespace(SentenceTransformer=factory),
                                     'huggingface_hub': SimpleNamespace(HfApi=api)}):
            E5Provider(revision='a' * 40)
        api.assert_not_called()
        self.assertTrue(factory.call_args.kwargs['local_files_only'])
        self.assertEqual(factory.call_count, 1)

    def test_missing_cache_downloads_the_same_pinned_revision(self):
        factory = Mock(side_effect=[OSError('not cached'), self.model()])
        with patch.dict(sys.modules, {'sentence_transformers': SimpleNamespace(SentenceTransformer=factory),
                                     'huggingface_hub': SimpleNamespace(HfApi=Mock())}):
            E5Provider(revision='a' * 40)
        self.assertEqual([call.kwargs['local_files_only'] for call in factory.call_args_list], [True, False])
        self.assertEqual({call.kwargs['revision'] for call in factory.call_args_list}, {'a' * 40})
