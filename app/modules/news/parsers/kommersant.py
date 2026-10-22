import re
from urllib.parse import urlsplit
from .base import SourceParser
from ..dto import SourceDTO

class KommersantParser(SourceParser):
    def __init__(self):
        super().__init__(SourceDTO('kommersant', 'Коммерсантъ', 'kommersant.ru', 'https://www.kommersant.ru/sitemaps/news.xml', 'https://www.kommersant.ru/RSS/news.xml'), ('.article_text_wrapper', '.doc__text'))

    def is_article(self, url):
        return bool(re.fullmatch('/doc/\\d+/?', urlsplit(url).path))
