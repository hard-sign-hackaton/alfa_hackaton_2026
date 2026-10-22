import re
from urllib.parse import urlsplit
from .base import SourceParser
from ..dto import SourceDTO

class VedomostiParser(SourceParser):
    def __init__(self):
        super().__init__(SourceDTO('vedomosti', 'Ведомости', 'vedomosti.ru', 'https://www.vedomosti.ru/sitemap.xml', 'https://www.vedomosti.ru/rss/news'), ('.article__body', '[itemprop="articleBody"]'))

    def is_article(self, url):
        return bool(re.search('/(news|articles)/\\d{4}/\\d{2}/\\d{2}/', urlsplit(url).path))
