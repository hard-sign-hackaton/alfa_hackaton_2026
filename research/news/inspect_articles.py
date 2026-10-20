import requests, concurrent.futures
from bs4 import BeautifulSoup
urls=['https://www.kommersant.ru/doc/9043090','https://www.vedomosti.ru/business/news/2026/10/20/1238594-tsena-na-gaz','https://www.interfax.ru/business/1123769']
def run(url):
 try:
  r=requests.get(url,timeout=20); r.raise_for_status(); r.encoding=r.apparent_encoding
  s=BeautifulSoup(r.text,'html.parser')
  print(url,r.status_code)
  for sel in ['.article_text_wrapper','.doc__text','.article__body','[itemprop="articleBody"]','article','script[type="application/ld+json"]']:
   ns=s.select(sel); print(sel,len(ns),sum(len(n.get_text()) for n in ns))
  from pathlib import Path
  Path('research/news/'+('kom_article' if 'kommersant' in url else 'ved_article' if 'vedomosti' in url else 'inter_article')+'.html').write_text(r.text,encoding='utf-8')
 except Exception as e: print(url,str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as p: list(p.map(run,urls))
