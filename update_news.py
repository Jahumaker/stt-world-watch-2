#!/usr/bin/env python3
import json, re, hashlib, html, os, sys, time, random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
ARTICLES_PATH = ROOT/'articles.json'
STATUS_PATH = ROOT/'status.json'
API = 'https://api.gdeltproject.org/api/v2/doc/doc'
UA = 'Mozilla/5.0 (compatible; STT-World-Watch/1.1; +https://github.com/Jahumaker/stt-world-watch)'

COUNTRY_MAP = {
 'Sweden':('Ruotsi','SE'),'Norway':('Norja','NO'),'Denmark':('Tanska','DK'),'Estonia':('Viro','EE'),
 'Latvia':('Latvia','LV'),'Lithuania':('Liettua','LT'),'Germany':('Saksa','DE'),'Austria':('Itävalta','AT'),
 'Switzerland':('Sveitsi','CH'),'Netherlands':('Alankomaat','NL'),'Belgium':('Belgia','BE'),'France':('Ranska','FR'),
 'United Kingdom':('Britannia','GB'),'Ireland':('Irlanti','IE'),'Poland':('Puola','PL'),'Czech Republic':('Tšekki','CZ'),
 'Slovakia':('Slovakia','SK'),'Italy':('Italia','IT'),'Spain':('Espanja','ES'),'Portugal':('Portugali','PT'),
 'Ukraine':('Ukraina','UA'),'Russia':('Venäjä','RU'),'United States':('Yhdysvallat','US'),'Canada':('Kanada','CA'),
 'Australia':('Australia','AU')
}
TLD_MAP = {'se':('Ruotsi','SE'),'no':('Norja','NO'),'dk':('Tanska','DK'),'ee':('Viro','EE'),'lv':('Latvia','LV'),'lt':('Liettua','LT'),'de':('Saksa','DE'),'at':('Itävalta','AT'),'ch':('Sveitsi','CH'),'nl':('Alankomaat','NL'),'be':('Belgia','BE'),'fr':('Ranska','FR'),'uk':('Britannia','GB'),'ie':('Irlanti','IE'),'pl':('Puola','PL'),'cz':('Tšekki','CZ'),'sk':('Slovakia','SK'),'it':('Italia','IT'),'es':('Espanja','ES'),'pt':('Portugali','PT'),'ua':('Ukraina','UA'),'ru':('Venäjä','RU'),'ca':('Kanada','CA'),'au':('Australia','AU')}
AGENCIES = ['Reuters','AP','AFP','TT','NTB','Ritzau','dpa','ANSA','EFE','APA','Belga','ANP','Keystone-SDA']
CLOSURE_WORDS = ['closure','closing','shutdown','crisis','restructur','layoff','avveck','läggs ned','nedlägg','kris','opphør','avvikl','sulgem','lõpet','lopett','lakkaut','tappio','убыт','сворач','закры','crise','fermet','chius','cierre']
AGENCY_WORDS = ['news agency','nyhetsbyrå','nyhetsbyrån','uudisteagentuur','nachrichtenagentur','agence de presse','agencia de noticias','agenzia di stampa','agencja prasowa','информагентств']


def nowiso(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def domain_of(url): return urlparse(url).netloc.lower().removeprefix('www.')
def normalize_title(t):
    t=html.unescape(t or '').lower().replace('’',"'").replace('‘',"'").replace('“','"').replace('”','"')
    t=re.sub(r'\s*[|–—-]\s*(reuters|ap|afp|tt|ntb|svd|aftonbladet|tv4|gp|err|postimees).*$', '', t, flags=re.I)
    t=re.sub(r'[^\w\såäöæøüéèáíóúßа-яё]+',' ',t,flags=re.I)
    return re.sub(r'\s+',' ',t).strip()
def stable_id(url): return hashlib.sha1(url.encode()).hexdigest()[:16]
def cluster_slug(title):
    n=normalize_title(title)
    return re.sub(r'[^a-z0-9åäöæøа-я]+','-',n,flags=re.I).strip('-')[:90] or stable_id(title)
def parse_seen(s):
    if not s: return nowiso()
    m=re.match(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z',s)
    if m: return f'{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}Z'
    try: return datetime.fromisoformat(s.replace('Z','+00:00')).isoformat()
    except: return nowiso()

def country_for(sourcecountry, domain):
    if sourcecountry in COUNTRY_MAP: return COUNTRY_MAP[sourcecountry]
    tld=domain.rsplit('.',1)[-1]
    return TLD_MAP.get(tld,(sourcecountry or 'Tuntematon',None))

def importance(domain):
    def matches(items): return any(domain==d or domain.endswith('.'+d) for d in items)
    if matches(CONFIG['high_priority_domains']): return 5
    if matches(CONFIG['major_domains']): return 4
    if matches(CONFIG['trade_domains']): return 3
    if matches(CONFIG['aggregator_domains']): return 1
    return 2

def excluded(domain): return any(domain==d or domain.endswith('.'+d) for d in CONFIG['exclude_domains'])

def fetch_meta(url):
    out={'description':None,'author':None,'text_hint':''}
    try:
        r=requests.get(url,headers={'User-Agent':UA},timeout=8,allow_redirects=True)
        if not r.ok or 'text/html' not in r.headers.get('content-type',''): return out
        soup=BeautifulSoup(r.text[:600000],'html.parser')
        desc=soup.find('meta',attrs={'property':'og:description'}) or soup.find('meta',attrs={'name':'description'})
        if desc: out['description']=desc.get('content','').strip()[:700]
        auth=soup.find('meta',attrs={'name':re.compile('author',re.I)})
        if auth: out['author']=auth.get('content','').strip()[:160]
        out['text_hint']=' '.join(soup.stripped_strings)[:6000]
    except Exception: pass
    return out

def infer_agency(domain, author, text):
    for d,name in CONFIG['agency_domains'].items():
        if domain==d or domain.endswith('.'+d): return name
    hay=f'{author or ""} {text or ""}'
    patterns={
      'TT':[r'\bWiktor Nummelin\b',r'\bTT\b'], 'NTB':[r'\bNTB\b'], 'Reuters':[r'\bReuters\b'],
      'AP':[r'Associated Press',r'\bAP\b'], 'AFP':[r'\bAFP\b'], 'Ritzau':[r'\bRitzau\b'], 'dpa':[r'\bdpa\b']
    }
    for name, pats in patterns.items():
        if any(re.search(p,hay,re.I) for p in pats): return name
    return None

def relevant(title, desc, text):
    hay=' '.join([title or '',desc or '',(text or '')[:2200]]).lower()
    stt = bool(re.search(r'\bstt(?:-lehtikuva)?\b',hay,re.I))
    agency_context = any(w in hay for w in AGENCY_WORDS)
    closure_context = any(w in hay for w in CLOSURE_WORDS)
    exact_context = any(p in hay for p in ['finnish news agency','finska nyhetsbyrån','finsk nyhetsbyrå','soome uudisteagentuur','finnische nachrichtenagentur','финское информагентство'])
    return stt and (exact_context or agency_context or closure_context)

def infer_type(domain, title, agency):
    low=(title or '').lower()
    if domain in CONFIG['aggregator_domains']: return 'AGGREGATOR'
    if any(w in low for w in ['debatt','opinion','comment','kommentar','kolumn']): return 'COMMENT'
    if agency and any(domain==d or domain.endswith('.'+d) for d in CONFIG['agency_domains']): return 'AGENCY'
    if agency: return 'SYNDICATED'
    return 'ORIGINAL'

def summary_fi(title, publisher, agency, typ):
    if typ=='COMMENT': return f'{publisher} julkaisi STT:tä koskevan kommentti- tai mielipidekirjoituksen. Avaa alkuperäinen juttu tarkkaa sisältöä varten.'
    if agency: return f'{publisher} julkaisi {agency}-aineistoa STT:n tilanteesta. Sovellus ryhmittelee saman uutistoimistotekstin muut julkaisut samaan nippuun.'
    return f'{publisher} julkaisi STT:n tilanteeseen liittyvän jutun. Automaattinen seuranta on tunnistanut sen STT:tä itseään käsitteleväksi osumaksi.'

def _gdelt_params(query, fmt='json'):
    return {
        'query': query,
        'mode': 'artlist',
        'format': fmt,
        'maxrecords': 75,
        'timespan': CONFIG.get('lookback', '3d'),
        'sort': 'datedesc'
    }

def _rss_to_articles(xml_text):
    """Convert GDELT's ArticleList RSS output to the same minimal shape as JSON."""
    root = ET.fromstring(xml_text)
    out = []
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        url = (item.findtext('link') or '').strip()
        if not title or not url:
            continue
        pub = (item.findtext('pubDate') or '').strip()
        seen = None
        if pub:
            try:
                seen = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat(timespec='seconds')
            except Exception:
                seen = None
        out.append({
            'url': url,
            'title': title,
            'domain': domain_of(url),
            'sourcecountry': None,
            'seendate': seen or nowiso()
        })
    return out

def search_gdelt(query):
    """
    Search GDELT gently.

    Primary path: JSON.
    If GDELT returns HTTP 429, HTML, an empty body or otherwise invalid JSON,
    retry with backoff. If JSON remains unavailable, fall back to GDELT's RSS
    ArticleList output, which contains the original article URLs and titles.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': UA,
        'Accept': 'application/json,text/plain,*/*'
    })

    last_error = None

    # JSON first.
    for attempt in range(1, 4):
        try:
            r = session.get(API, params=_gdelt_params(query, 'json'), timeout=45)

            if r.status_code == 429:
                retry_after = r.headers.get('Retry-After')
                try:
                    wait = int(retry_after) if retry_after else 15 * (2 ** (attempt - 1))
                except ValueError:
                    wait = 15 * (2 ** (attempt - 1))
                wait = min(max(wait, 10), 60)
                last_error = f'HTTP 429, retry {attempt}/3 after {wait}s'
                print(f'GDELT JSON: {last_error}')
                time.sleep(wait)
                continue

            r.raise_for_status()
            body = r.text.lstrip()
            ctype = (r.headers.get('content-type') or '').lower()

            # GDELT occasionally returns a 200 response with HTML or an empty
            # body during load. Do not hand that to json(), because it produces
            # the unhelpful "Expecting value" exception.
            if not body:
                raise RuntimeError('empty response body')
            if body.startswith('<!DOCTYPE') or body.startswith('<html') or 'text/html' in ctype:
                raise RuntimeError('HTML returned instead of JSON')

            data = r.json()
            return data.get('articles', [])

        except Exception as e:
            last_error = str(e)
            if attempt < 3:
                wait = 8 * attempt
                print(f'GDELT JSON unavailable ({last_error}); retrying in {wait}s')
                time.sleep(wait)

    # RSS fallback. GDELT documents RSS as an ArticleList output format.
    print(f'GDELT JSON unavailable after retries ({last_error}); trying RSS fallback.')
    rss_headers = {
        'User-Agent': UA,
        'Accept': 'application/rss+xml,application/xml,text/xml,*/*'
    }
    for attempt in range(1, 3):
        try:
            r = session.get(API, params=_gdelt_params(query, 'rss'),
                            headers=rss_headers, timeout=45)
            if r.status_code == 429:
                wait = 20 * attempt
                print(f'GDELT RSS rate-limited; retrying in {wait}s')
                time.sleep(wait)
                continue
            r.raise_for_status()
            body = r.text.lstrip()
            if not body or body.startswith('<!DOCTYPE html') or body.startswith('<html'):
                raise RuntimeError('HTML/empty response returned instead of RSS')
            articles = _rss_to_articles(r.text)
            print(f'GDELT RSS fallback returned {len(articles)} articles.')
            return articles
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(10)

    raise RuntimeError(f'GDELT JSON and RSS both unavailable: {last_error}')


def gdelt_queries():
    # One broad multilingual request replaces the old 14 rapid-fire requests.
    # If it yields no candidates, a single English backstop query is allowed.
    primary = (
        'STT ("Finnish news agency" OR "Finnish News Agency" OR '
        '"finska nyhetsbyrån" OR "finsk nyhetsbyrå" OR '
        '"Soome uudisteagentuur" OR "finnische Nachrichtenagentur" OR '
        '"agence de presse finlandaise" OR "agencia de noticias finlandesa" OR '
        '"agenzia di stampa finlandese" OR "fińska agencja prasowa" OR '
        '"финское информационное агентство")'
    )
    fallback = 'STT "news agency" (closure OR crisis OR restructuring OR shutdown OR losses)'
    return primary, fallback

def title_similarity(a,b): return SequenceMatcher(None,normalize_title(a),normalize_title(b)).ratio()

def assign_clusters(items):
    groups=[]
    for item in sorted(items,key=lambda x:x.get('published_at','')):
        best=None
        for leader in groups:
            sim=title_similarity(item['title'],leader['title'])
            dt=abs(datetime.fromisoformat(item['published_at'].replace('Z','+00:00')).timestamp()-datetime.fromisoformat(leader['published_at'].replace('Z','+00:00')).timestamp())/3600
            if sim>=0.90 and dt<=72: best=leader; break
        if best: item['cluster_id']=best['cluster_id']
        else:
            item['cluster_id']=cluster_slug(item['title']); groups.append(item)
    # If a cluster has >1 domains and an agency marker, mark non-agency-domain copies as syndicated.
    by={}
    for x in items: by.setdefault(x['cluster_id'],[]).append(x)
    for group in by.values():
        agencies=[x.get('agency') for x in group if x.get('agency')]
        agency=agencies[0] if agencies else None
        if len({x['domain'] for x in group})>1 and agency:
            for x in group:
                if x['type'] not in ('COMMENT','AGGREGATOR','AGENCY'): x['type']='SYNDICATED'
    return items

def write_actions_summary(candidates_count, new_count, errors):
    '''Write run details to the Actions run summary without changing the repo.'''
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not summary_path:
        return
    lines = [
        '## STT World Watch',
        '',
        f'- Candidate URLs checked: **{candidates_count}**',
        f'- New relevant articles added: **{new_count}**',
        f'- Run time (UTC): **{nowiso()}**',
    ]
    if errors:
        lines += ['', '### Warnings', *[f'- {e}' for e in errors[:10]]]
    with open(summary_path, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    old=json.loads(ARTICLES_PATH.read_text(encoding='utf-8')) if ARTICLES_PATH.exists() else []
    by_url={x['url']:x for x in old}
    candidates={}
    errors=[]
    primary, fallback = gdelt_queries()

    # Small jitter prevents thousands of scheduled jobs around the world from
    # hitting the public endpoint on exactly the same second.
    time.sleep(random.uniform(2,8))

    try:
        results=search_gdelt(primary)
        for x in results:
            url=x.get('url'); title=(x.get('title') or '').strip()
            if not url or not title: continue
            domain=x.get('domain') or domain_of(url)
            if excluded(domain): continue
            candidates[url]=(x,title,domain)
    except Exception as e:
        errors.append(f'Primary GDELT search: {e}')

    # Only make a second GDELT request when the first one succeeded but returned
    # no usable candidates. This keeps normal hourly load to one API request.
    if not candidates and not errors:
        time.sleep(15)
        try:
            for x in search_gdelt(fallback):
                url=x.get('url'); title=(x.get('title') or '').strip()
                if not url or not title: continue
                domain=x.get('domain') or domain_of(url)
                if excluded(domain): continue
                candidates[url]=(x,title,domain)
        except Exception as e:
            errors.append(f'Fallback GDELT search: {e}')
    new=[]
    for url,(x,title,domain) in candidates.items():
        if url in by_url: continue
        meta=fetch_meta(url)
        if not relevant(title,meta['description'],meta['text_hint']): continue
        country,cc=country_for(x.get('sourcecountry'),domain)
        author=meta['author']
        agency=infer_agency(domain,author,meta['text_hint'])
        typ=infer_type(domain,title,agency)
        publisher=(x.get('domain') or domain).removeprefix('www.')
        article={
          'id':stable_id(url),'cluster_id':cluster_slug(title),'title':title,'title_fi':None,'url':url,
          'domain':domain,'publisher':publisher,'country':country,'country_code':cc,
          'published_at':parse_seen(x.get('seendate')),'author':author,'agency':agency,'type':typ,
          'importance':importance(domain),'summary_fi':summary_fi(title,publisher,agency,typ),
          'first_seen':nowiso(),'seed':False
        }
        new.append(article)

    # Important for GitHub Pages Free: an hourly check with zero new articles must
    # not touch tracked files. That means no commit and therefore no needless
    # Pages rebuild. The Actions run itself still shows the check in its summary.
    if not new:
        print(f'Checked {len(candidates)} candidate URLs, added 0 new articles. No repository files changed.')
        if errors: print('Warnings:',*errors,sep='\n- ')
        write_actions_summary(len(candidates), 0, errors)
        return

    all_items=assign_clusters(old+new)
    # Preserve most recent first in JSON for easy inspection.
    all_items.sort(key=lambda x:x.get('published_at',''),reverse=True)
    ARTICLES_PATH.write_text(json.dumps(all_items,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')

    # Persist status only when the shared data actually changes. The UI therefore
    # labels this as the latest DATA UPDATE, not the latest hourly check.
    status={
      'last_data_update':nowiso(),
      'last_success':nowiso(),
      'new_count':len(new),
      'source_count':len(candidates),
      'error':'; '.join(errors)[:1200] or None
    }
    STATUS_PATH.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    print(f'Checked {len(candidates)} candidate URLs, added {len(new)} new articles.')
    if errors: print('Warnings:',*errors,sep='\n- ')
    write_actions_summary(len(candidates), len(new), errors)

if __name__=='__main__': main()
