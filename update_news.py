#!/usr/bin/env python3
import json
import re
import hashlib
import html
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs, unquote
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ARTICLES_PATH = ROOT / "articles.json"
STATUS_PATH = ROOT / "status.json"

UA = (
    "Mozilla/5.0 (compatible; STT-World-Watch/2.0; "
    "+https://github.com/Jahumaker/stt-world-watch)"
)

BING_URL = "https://www.bing.com/news/search"
GOOGLE_URL = "https://news.google.com/rss/search"

# The search is deliberately split into a small number of precise multilingual
# queries. Bing News RSS is primary; Google News RSS is used per-query when Bing
# fails or returns no usable results. No API key is required.
SEARCH_SPECS = [
    ('"Finnish news agency" STT', "en-US", "US", "en"),
    ('"finska nyhetsbyrån" STT', "sv-SE", "SE", "sv"),
    ('"finsk nyhetsbyrå" STT', "nb-NO", "NO", "no"),
    ('"Soome uudisteagentuur" STT', "et-EE", "EE", "et"),
    ('"finnische Nachrichtenagentur" STT', "de-DE", "DE", "de"),
    ('"fińska agencja prasowa" STT', "pl-PL", "PL", "pl"),
    ('"финское информационное агентство" STT', "ru-RU", "RU", "ru"),
    ('"agence de presse finlandaise" STT', "fr-FR", "FR", "fr"),
]

COUNTRY_MAP = {
    "Sweden": ("Ruotsi", "SE"),
    "Norway": ("Norja", "NO"),
    "Denmark": ("Tanska", "DK"),
    "Estonia": ("Viro", "EE"),
    "Latvia": ("Latvia", "LV"),
    "Lithuania": ("Liettua", "LT"),
    "Germany": ("Saksa", "DE"),
    "Austria": ("Itävalta", "AT"),
    "Switzerland": ("Sveitsi", "CH"),
    "Netherlands": ("Alankomaat", "NL"),
    "Belgium": ("Belgia", "BE"),
    "France": ("Ranska", "FR"),
    "United Kingdom": ("Britannia", "GB"),
    "Ireland": ("Irlanti", "IE"),
    "Poland": ("Puola", "PL"),
    "Czech Republic": ("Tšekki", "CZ"),
    "Slovakia": ("Slovakia", "SK"),
    "Italy": ("Italia", "IT"),
    "Spain": ("Espanja", "ES"),
    "Portugal": ("Portugali", "PT"),
    "Ukraine": ("Ukraina", "UA"),
    "Russia": ("Venäjä", "RU"),
    "United States": ("Yhdysvallat", "US"),
    "Canada": ("Kanada", "CA"),
    "Australia": ("Australia", "AU"),
}

TLD_MAP = {
    "se": ("Ruotsi", "SE"),
    "no": ("Norja", "NO"),
    "dk": ("Tanska", "DK"),
    "ee": ("Viro", "EE"),
    "lv": ("Latvia", "LV"),
    "lt": ("Liettua", "LT"),
    "de": ("Saksa", "DE"),
    "at": ("Itävalta", "AT"),
    "ch": ("Sveitsi", "CH"),
    "nl": ("Alankomaat", "NL"),
    "be": ("Belgia", "BE"),
    "fr": ("Ranska", "FR"),
    "uk": ("Britannia", "GB"),
    "ie": ("Irlanti", "IE"),
    "pl": ("Puola", "PL"),
    "cz": ("Tšekki", "CZ"),
    "sk": ("Slovakia", "SK"),
    "it": ("Italia", "IT"),
    "es": ("Espanja", "ES"),
    "pt": ("Portugali", "PT"),
    "ua": ("Ukraina", "UA"),
    "ru": ("Venäjä", "RU"),
    "ca": ("Kanada", "CA"),
    "au": ("Australia", "AU"),
}

DOMAIN_COUNTRY = {
    "ua.news": ("Ukraina", "UA"),
    "apnews.com": ("Yhdysvallat", "US"),
    "bbc.com": ("Britannia", "GB"),
    "bbc.co.uk": ("Britannia", "GB"),
    "theguardian.com": ("Britannia", "GB"),
    "ft.com": ("Britannia", "GB"),
    "nytimes.com": ("Yhdysvallat", "US"),
    "washingtonpost.com": ("Yhdysvallat", "US"),
    "reuters.com": ("Kansainvälinen", None),
    "afp.com": ("Kansainvälinen", None),
}

CLOSURE_WORDS = [
    "closure", "closing", "shutdown", "crisis", "restructur", "layoff",
    "avveck", "läggs ned", "nedlägg", "kris", "upphöra", "opphør", "avvikl",
    "sulgem", "lõpet", "lopett", "lakkaut", "tappio",
    "убыт", "сворач", "закры", "crise", "fermet", "chius", "cierre",
]
AGENCY_WORDS = [
    "news agency", "nyhetsbyrå", "nyhetsbyrån", "uudisteagentuur",
    "nachrichtenagentur", "agence de presse", "agencia de noticias",
    "agenzia di stampa", "agencja prasowa", "информагентств",
]


def nowiso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def domain_of(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def normalize_title(t):
    t = html.unescape(t or "").lower()
    t = (
        t.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    t = re.sub(
        r"\s*[|–—-]\s*(reuters|ap|afp|tt|ntb|svd|aftonbladet|tv4|gp|err|postimees).*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"[^\w\såäöæøüéèáíóúßа-яё]+", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def stable_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def cluster_slug(title):
    n = normalize_title(title)
    return re.sub(r"[^a-z0-9åäöæøа-я]+", "-", n, flags=re.I).strip("-")[:90] or stable_id(title)


def parse_pubdate(value):
    if not value:
        return nowiso()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return nowiso()


def country_for(domain, sourcecountry=None):
    if sourcecountry in COUNTRY_MAP:
        return COUNTRY_MAP[sourcecountry]
    for d, result in DOMAIN_COUNTRY.items():
        if domain == d or domain.endswith("." + d):
            return result
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    return TLD_MAP.get(tld, ("Tuntematon", None))


def importance(domain):
    def matches(items):
        return any(domain == d or domain.endswith("." + d) for d in items)

    if matches(CONFIG.get("high_priority_domains", [])):
        return 5
    if matches(CONFIG.get("major_domains", [])):
        return 4
    if matches(CONFIG.get("trade_domains", [])):
        return 3
    if matches(CONFIG.get("aggregator_domains", [])):
        return 1
    return 2


def excluded(domain):
    return any(
        domain == d or domain.endswith("." + d)
        for d in CONFIG.get("exclude_domains", [])
    )


def localname(tag):
    return tag.rsplit("}", 1)[-1].lower()


def clean_html_text(value):
    if not value:
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").stripped_strings)


def unwrap_bing_url(url):
    """Bing RSS often wraps the publisher URL in /news/apiclick.aspx?url=..."""
    try:
        p = urlparse(url)
        if p.netloc.lower().endswith("bing.com") and "apiclick" in p.path.lower():
            q = parse_qs(p.query)
            target = q.get("url", [None])[0]
            if target:
                return unquote(target)
    except Exception:
        pass
    return url


def fetch_xml(url, params, attempts=3):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        }
    )
    last = None
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(url, params=params, timeout=35)
            if r.status_code == 429:
                wait = 8 * attempt
                last = f"HTTP 429; retry in {wait}s"
                time.sleep(wait)
                continue
            r.raise_for_status()
            body = r.text.lstrip()
            ctype = (r.headers.get("content-type") or "").lower()
            if not body:
                raise RuntimeError("empty response")
            if body.lower().startswith("<!doctype html") or body.lower().startswith("<html"):
                raise RuntimeError("HTML returned instead of RSS")
            if "xml" not in ctype and not body.startswith("<?xml") and "<rss" not in body[:500].lower():
                raise RuntimeError(f"unexpected content type {ctype or 'unknown'}")
            return r.text
        except Exception as e:
            last = str(e)
            if attempt < attempts:
                time.sleep(5 * attempt)
    raise RuntimeError(last or "RSS request failed")


def parse_rss(xml_text, engine):
    root = ET.fromstring(xml_text)
    items = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = clean_html_text(item.findtext("description") or "")
        pubdate = (item.findtext("pubDate") or "").strip()

        source_name = ""
        source_url = ""

        # Google uses <source url="https://publisher.example/">Publisher</source>.
        # Bing may use namespaced source/provider elements.
        for child in list(item):
            ln = localname(child.tag)
            if ln in ("source", "provider"):
                txt = (child.text or "").strip()
                if txt:
                    source_name = txt
                if child.attrib.get("url"):
                    source_url = child.attrib.get("url", "").strip()

        if not title or not link:
            continue

        if engine == "bing":
            direct_url = unwrap_bing_url(link)
            # If Bing gave us a direct publisher URL, trust its domain.
            source_domain = domain_of(direct_url)
        else:
            direct_url = link
            source_domain = domain_of(source_url) if source_url else domain_of(link)

        if not source_name:
            source_name = source_domain or engine.title()

        # Google News commonly appends " - Publisher" to the RSS title.
        suffix = f" - {source_name}"
        if engine == "google" and source_name and title.endswith(suffix):
            title = title[: -len(suffix)].strip()

        items.append(
            {
                "url": direct_url,
                "discovery_url": link,
                "title": title,
                "description": desc,
                "published_at": parse_pubdate(pubdate),
                "publisher": source_name,
                "domain": source_domain,
                "engine": engine,
            }
        )

    return items


def search_bing(query, market):
    xml_text = fetch_xml(
        BING_URL,
        {
            "q": query,
            "format": "rss",
            "qft": 'sortbydate="1"',
            "setlang": market,
        },
    )
    return parse_rss(xml_text, "bing")


def search_google(query, hl, gl, lang):
    # "when:3d" keeps a fallback feed focused on fresh coverage.
    xml_text = fetch_xml(
        GOOGLE_URL,
        {
            "q": f"{query} when:3d",
            "hl": hl,
            "gl": gl,
            "ceid": f"{gl}:{lang}",
        },
    )
    return parse_rss(xml_text, "google")


def fetch_meta(url):
    out = {"description": None, "author": None, "text_hint": "", "final_url": url}
    if not url or domain_of(url) in ("news.google.com", "www.google.com"):
        return out
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA},
            timeout=10,
            allow_redirects=True,
        )
        out["final_url"] = r.url or url
        if not r.ok or "text/html" not in (r.headers.get("content-type") or ""):
            return out
        soup = BeautifulSoup(r.text[:700000], "html.parser")
        desc = (
            soup.find("meta", attrs={"property": "og:description"})
            or soup.find("meta", attrs={"name": "description"})
        )
        if desc:
            out["description"] = desc.get("content", "").strip()[:900]
        auth = soup.find("meta", attrs={"name": re.compile("author", re.I)})
        if auth:
            out["author"] = auth.get("content", "").strip()[:160]
        out["text_hint"] = " ".join(soup.stripped_strings)[:7000]
    except Exception:
        pass
    return out


def infer_agency(domain, publisher, author, text):
    for d, name in CONFIG.get("agency_domains", {}).items():
        if domain == d or domain.endswith("." + d):
            return name

    hay = f"{publisher or ''} {author or ''} {text or ''}"
    patterns = {
        "TT": [r"\bWiktor Nummelin\b", r"\bTT\b"],
        "NTB": [r"\bNTB\b"],
        "Reuters": [r"\bReuters\b"],
        "AP": [r"Associated Press", r"\bAP\b"],
        "AFP": [r"\bAFP\b"],
        "Ritzau": [r"\bRitzau\b"],
        "dpa": [r"\bdpa\b"],
    }
    for name, pats in patterns.items():
        if any(re.search(p, hay, re.I) for p in pats):
            return name
    return None


def relevant(title, feed_desc, meta_desc, text):
    hay = " ".join(
        [title or "", feed_desc or "", meta_desc or "", (text or "")[:3000]]
    ).lower()
    stt = bool(re.search(r"\bstt(?:-lehtikuva)?\b", hay, re.I))
    agency_context = any(w in hay for w in AGENCY_WORDS)
    closure_context = any(w in hay for w in CLOSURE_WORDS)
    exact_context = any(
        p in hay
        for p in [
            "finnish news agency",
            "finska nyhetsbyrån",
            "finsk nyhetsbyrå",
            "soome uudisteagentuur",
            "finnische nachrichtenagentur",
            "fińska agencja prasowa",
            "agence de presse finlandaise",
            "финское информационное агентство",
        ]
    )
    return stt and (exact_context or agency_context or closure_context)


def infer_type(domain, title, publisher, agency):
    low = (title or "").lower()
    if domain in CONFIG.get("aggregator_domains", []):
        return "AGGREGATOR"
    if any(w in low for w in ["debatt", "opinion", "comment", "kommentar", "kolumn"]):
        return "COMMENT"
    if agency and any(
        domain == d or domain.endswith("." + d)
        for d in CONFIG.get("agency_domains", {})
    ):
        return "AGENCY"
    if agency:
        return "SYNDICATED"
    return "ORIGINAL"


def summary_fi(publisher, agency, typ):
    if typ == "COMMENT":
        return (
            f"{publisher} julkaisi STT:tä koskevan kommentti- tai mielipidekirjoituksen. "
            "Avaa alkuperäinen juttu tarkkaa sisältöä varten."
        )
    if agency:
        return (
            f"{publisher} julkaisi {agency}-aineistoa STT:n tilanteesta. "
            "Saman uutistoimistotekstin muut julkaisut ryhmitellään samaan nippuun."
        )
    return (
        f"{publisher} julkaisi STT:n tilanteeseen liittyvän jutun. "
        "Automaattinen seuranta tunnisti sen STT:tä itseään käsitteleväksi osumaksi."
    )


def title_similarity(a, b):
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def assign_clusters(items):
    groups = []
    for item in sorted(items, key=lambda x: x.get("published_at", "")):
        best = None
        for leader in groups:
            sim = title_similarity(item["title"], leader["title"])
            try:
                dt = abs(
                    datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")).timestamp()
                    - datetime.fromisoformat(leader["published_at"].replace("Z", "+00:00")).timestamp()
                ) / 3600
            except Exception:
                dt = 999
            if sim >= 0.88 and dt <= 96:
                best = leader
                break
        if best:
            item["cluster_id"] = best["cluster_id"]
        else:
            item["cluster_id"] = cluster_slug(item["title"])
            groups.append(item)

    by_cluster = {}
    for x in items:
        by_cluster.setdefault(x["cluster_id"], []).append(x)

    # Even when the RSS feed doesn't expose the wire-service credit, identical
    # headlines across several publishers are treated as a syndication cluster.
    for group in by_cluster.values():
        domains = {x.get("domain") for x in group if x.get("domain")}
        agencies = [x.get("agency") for x in group if x.get("agency")]
        agency = agencies[0] if agencies else None
        if len(domains) > 1:
            for x in group:
                if agency and not x.get("agency"):
                    x["agency"] = agency
                if x["type"] not in ("COMMENT", "AGGREGATOR", "AGENCY"):
                    x["type"] = "SYNDICATED"

    return items


def write_actions_summary(candidates_count, new_count, errors, engines):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## STT World Watch",
        "",
        f"- Candidate URLs checked: **{candidates_count}**",
        f"- New relevant articles added: **{new_count}**",
        f"- Search sources used: **{', '.join(sorted(engines)) if engines else 'none'}**",
        f"- Run time (UTC): **{nowiso()}**",
    ]
    if errors:
        lines += ["", "### Warnings", *[f"- {e}" for e in errors[:16]]]
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    old = (
        json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
        if ARTICLES_PATH.exists()
        else []
    )
    by_url = {x["url"]: x for x in old if x.get("url")}
    candidates = {}
    errors = []
    engines_used = set()

    for idx, (query, hl, gl, lang) in enumerate(SEARCH_SPECS, start=1):
        bing_results = []
        try:
            bing_results = search_bing(query, hl)
            if bing_results:
                engines_used.add("Bing News RSS")
        except Exception as e:
            errors.append(f'Bing {query}: {e}')

        # Use Google for this query when Bing failed or returned nothing. This
        # gives us a second discovery source without doubling every normal run.
        results = bing_results
        if not results:
            try:
                results = search_google(query, hl, gl, lang)
                if results:
                    engines_used.add("Google News RSS")
            except Exception as e:
                errors.append(f'Google {query}: {e}')

        for x in results:
            url = x.get("url")
            title = (x.get("title") or "").strip()
            domain = x.get("domain") or domain_of(url)
            if not url or not title:
                continue
            if domain and excluded(domain):
                continue

            # Prefer an original publisher URL. Google fallback URLs may remain
            # news.google.com; they are still clickable and retain publisher info.
            key = url
            candidates[key] = x

        # Be polite to public RSS endpoints.
        if idx < len(SEARCH_SPECS):
            time.sleep(1.5)

    new = []

    for url, x in candidates.items():
        if url in by_url:
            continue

        title = x["title"]
        feed_desc = x.get("description") or ""
        publisher = x.get("publisher") or x.get("domain") or "Tuntematon media"
        domain = x.get("domain") or domain_of(url)

        meta = fetch_meta(url)
        final_url = meta.get("final_url") or url

        # If Bing's wrapper eventually redirected to a better direct URL, use it.
        final_domain = domain_of(final_url)
        if final_domain and final_domain not in ("www.bing.com", "bing.com"):
            url = final_url
            domain = final_domain

        if domain and excluded(domain):
            continue

        if not relevant(title, feed_desc, meta["description"], meta["text_hint"]):
            continue

        country, cc = country_for(domain)
        author = meta["author"]
        agency = infer_agency(
            domain,
            publisher,
            author,
            " ".join([feed_desc, meta["description"] or "", meta["text_hint"] or ""]),
        )
        typ = infer_type(domain, title, publisher, agency)

        article = {
            "id": stable_id(url),
            "cluster_id": cluster_slug(title),
            "title": title,
            "title_fi": None,
            "url": url,
            "domain": domain,
            "publisher": publisher,
            "country": country,
            "country_code": cc,
            "published_at": x.get("published_at") or nowiso(),
            "author": author,
            "agency": agency,
            "type": typ,
            "importance": importance(domain),
            "summary_fi": summary_fi(publisher, agency, typ),
            "first_seen": nowiso(),
            "seed": False,
        }

        # Avoid adding the same direct URL twice if two queries found it.
        if article["url"] not in by_url and not any(n["url"] == article["url"] for n in new):
            new.append(article)

    if not new:
        print(
            f"Checked {len(candidates)} candidate URLs, added 0 new articles. "
            "No repository files changed."
        )
        if errors:
            print("Warnings:", *errors, sep="\n- ")
        write_actions_summary(len(candidates), 0, errors, engines_used)
        return

    all_items = assign_clusters(old + new)
    all_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    ARTICLES_PATH.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    status = {
        "last_data_update": nowiso(),
        "last_success": nowiso(),
        "new_count": len(new),
        "source_count": len(candidates),
        "error": "; ".join(errors)[:1200] or None,
    }
    STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Checked {len(candidates)} candidate URLs, added {len(new)} new articles.")
    if errors:
        print("Warnings:", *errors, sep="\n- ")
    write_actions_summary(len(candidates), len(new), errors, engines_used)


if __name__ == "__main__":
    main()
