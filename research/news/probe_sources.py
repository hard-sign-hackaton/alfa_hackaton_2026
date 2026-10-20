import concurrent.futures, requests, xml.etree.ElementTree as ET, json
from pathlib import Path
from datetime import datetime, timezone
SOURCES = {
 'rbc': 'https://rssexport.rbc.ru/rbcnews/news/30/full.rss',
 'rbc_static': 'https://static.feed.rbc.ru/rbc/internal/rss.rbc.ru/rbc.ru/news.rss',
 'kommersant': 'https://www.kommersant.ru/RSS/news.xml',
 'vedomosti': 'https://www.vedomosti.ru/rss/news',
 'interfax': 'https://www.interfax.ru/rss.asp',
 'tass': 'https://tass.ru/rss/v2.xml',
}
OUT=Path(__file__).parent

def probe(pair):
 name,url=pair
 result={'source':name,'requested_url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=25,headers={'User-Agent':'AlfaHackNewsResearch/0.1'})
  result.update(status=r.status_code,final_url=r.url,content_type=r.headers.get('Content-Type'),bytes=len(r.content))
  r.raise_for_status()
  root=ET.fromstring(r.content)
  items=root.findall('.//item')
  result['items']=len(items)
  result['examples']=[{k: i.findtext(k) for k in ['title','link','pubDate','description','category']} for i in items[:12]]
  (OUT/(name+'.xml')).write_bytes(r.content)
 except Exception as e: result['error']=str(e)
 return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(probe,SOURCES.items()))
 (OUT/'source_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 for r in results:
  print(r['source'],r.get('status'),r.get('items'),r.get('error',''))
  for i in r.get('examples',[])[:4]: print(' ',i['title'],i['link'])
