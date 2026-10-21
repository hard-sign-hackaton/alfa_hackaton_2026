import re
from urllib.parse import urlsplit
from .base import SourceParser
from ..dto import SourceDTO

class InterfaxParser(SourceParser):
    def __init__(self):
        super().__init__(SourceDTO('interfax', 'Интерфакс', 'interfax.ru', 'https://www.interfax.ru/SEO_SiteMapIndex.xml', 'https://www.interfax.ru/rss.asp'), ('[itemprop="articleBody"]', '.text'))

    def is_article(self, url):
        return bool(re.fullmatch('/[a-z-]+/\\d+/?', urlsplit(url).path))
