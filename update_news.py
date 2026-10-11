#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
ARTICLES_PATH = ROOT / "articles.json"
STATUS_PATH = ROOT / "status.json"

FINNISH_DOMAINS = {
    "stt.fi", "sttinfo.fi", "yle.fi", "hs.fi", "is.fi", "iltalehti.fi",
    "mtvuutiset.fi", "helsinkitimes.fi", "verkkouutiset.fi", "demokraatti.fi",
}

COUNTRY_CODES = {
    "Ruotsi": "SE", "Norja": "NO", "Tanska": "DK", "Viro": "EE",
    "Latvia": "LV", "Liettua": "LT", "Saksa": "DE", "Itävalta": "AT",
    "Sveitsi": "CH", "Alankomaat": "NL", "Belgia": "BE", "Ranska": "FR",
    "Britannia": "GB", "Irlanti": "IE", "Puola": "PL", "Tšekki": "CZ",
    "Slovakia": "SK", "Italia": "IT", "Espanja": "ES", "Portugali": "PT",
    "Ukraina": "UA", "Venäjä": "RU", "Yhdysvallat": "US", "Kanada": "CA",
    "Australia": "AU", "Slovenia": "SI", "Kroatia": "HR",
    "Bosnia ja Hertsegovina": "BA", "Serbia": "RS", "Kreikka": "GR",
    "Kansainvälinen": None,
}

WATCHLIST = """
Seuraa erityisen tarkasti — mutta älä rajoitu näihin:
- European Commission, European Parliament, Council of Europe, EANA, EFJ, News Media Coalition.
- Euroopan kansalliset uutistoimistot ja niiden johto: TT, NTB, Ritzau, dpa, Belga,
  AFP, Reuters, AP, PA Media, ANP, APA, Keystone-SDA, EFE, ANSA, Lusa, STA, Hina,
  FENA, Beta sekä muut EANA-jäsenet.
- Media-alan ammattijulkaisut, journalistiliitot ja lehdistönvapausjärjestöt.
- Vaikutusvaltaiset EU- ja kansallisen tason poliitikot, mediajohtajat, journalistit,
  tutkijat ja turvallisuus-/disinformaatioasiantuntijat silloin, kun julkaisu liittyy
  selvästi tähän tapaukseen tai kansallisen uutistoimistoinfrastruktuurin katoamiseen.
- Jo keskustelussa esiintyneet nimet: Tina Mari Flem, Hans Vandendriessche,
  Sebastian Raabe, Clive Marshall, Éric Scherer, Aimilios Perdikaris, Alexandru Giboi.
""".strip()

EVENT_CARD = """
SEURATTAVA TAPAHTUMA
Suomen kansallinen uutistoimisto STT ilmoitti 30.9.2026 tilanteesta, jossa sen
journalistinen uutis- ja kuvatoiminta voi päättyä. Taustalla ovat pitkäaikaiset
taloudelliset vaikeudet, merkittävän asiakkuuden päättyminen, omistajien
ratkaisuyritykset sekä keskustelu mahdollisesta julkisesta tuesta.

Kansainvälinen keskustelu on laajentunut itse STT:tä laajemmaksi. Siinä on käsitelty
kansallisten uutistoimistojen merkitystä alkuperäisjournalismille, mediapluralismille,
alueellisille medioille, demokratian kriisinkestävyydelle, informaatioturvallisuudelle
ja disinformaation torjunnalle.

Tavoitteena on löytää myös sellaiset merkittävät kannanotot, jotka eivät mainitse
STT:tä nimeltä mutta jotka kontekstin, ajoituksen, linkityksen, keskusteluketjun tai
muun luotettavan näytön perusteella hyvin todennäköisesti kommentoivat juuri tätä
tapausta. Geneeristä puhetta mediasta tai uutistoimistoista EI saa yhdistää STT:hen
ilman konkreettista kontekstuaalista perustetta.
""".strip()

SCHEMA = {
    "type": "object",
    "properties": {
        "run_summary_fi": {"type": "string"},
        "search_notes_fi": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "title_fi": {"type": ["string", "null"]},
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "domain": {"type": ["string", "null"]},
                    "country": {"type": "string"},
                    "country_code": {"type": ["string", "null"]},
                    "published_at": {"type": ["string", "null"]},
                    "date_note": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "author_role": {"type": ["string", "null"]},
                    "agency": {"type": ["string", "null"]},
                    "platform": {"type": ["string", "null"]},
                    "type": {
                        "type": "string",
                        "enum": [
                            "ORIGINAL", "AGENCY", "SYNDICATED", "COMMENT",
                            "FOLLOW-UP", "AGGREGATOR", "STATEMENT",
                            "SOCIAL_POST", "ORG_RELEASE"
                        ]
                    },
                    "match_class": {
                        "type": "string",
                        "enum": ["CONFIRMED", "STRONG_MATCH", "POSSIBLE_MATCH"]
                    },
                    "direct_stt_reference": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "summary_fi": {"type": "string"},
                    "reason_fi": {"type": "string"},
                    "history_action": {
                        "type": "string",
                        "enum": ["NEW", "UPDATE_EXISTING", "NEW_SYNDICATION"]
                    },
                    "history_match_id": {"type": ["string", "null"]},
                    "history_match_reason_fi": {"type": ["string", "null"]},
                    "same_as_url": {"type": ["string", "null"]}
                },
                "required": [
                    "title", "title_fi", "url", "publisher", "domain", "country",
                    "country_code", "published_at", "date_note", "author",
                    "author_role", "agency", "platform", "type", "match_class",
                    "direct_stt_reference", "confidence", "importance", "summary_fi",
                    "reason_fi", "history_action", "history_match_id",
                    "history_match_reason_fi", "same_as_url"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["run_summary_fi", "search_notes_fi", "items"],
    "additionalProperties": False
}

SYSTEM = """
Olet STT World Watch -seuranta-agentti suomalaiselle uutistoimitukselle.
Tehtäväsi on tehdä journalistisesti tarkka kansainvälinen mediaseuranta. Käytä
web-hakua aktiivisesti ja monikielisesti. Etsi alkuperäislähteitä, älä vain hakutulos-
otsikoita. Etsi myös julkisia somepostauksia silloin kun ne ovat web-haulla löydettävissä.

Älä keksi linkkejä, julkaisuja, päivämääriä, titteleitä tai yhteyksiä. Palauta vain
osumia, joille löysit todellisen verkkolähteen. Jos yhteys STT-tapaukseen on epäsuora,
luokittele se STRONG_MATCH tai POSSIBLE_MATCH ja kerro reason_fi-kentässä täsmällisesti,
mihin yhteys perustuu. Jos näyttö ei riitä, jätä osuma pois.

Merkittävyydessä henkilön/aseman paino on tärkeä: esimerkiksi korkean tason EU-päättäjän,
uutistoimiston päätoimittajan tai suuren journalistijärjestön kannanotto voi olla 5/5,
vaikka kyseessä olisi vain yksi julkinen somepostaus. Älä kuitenkaan nosta geneeristä
kommenttia STT-osumaksi vain kirjoittajan aseman vuoksi.

Erottele syndikointi omasta uutisesta. Jos löydät uuden julkaisun jo tunnetusta
uutistoimistotekstistä, palauta se SYNDICATED-tyyppisenä ja aseta same_as_url tunnetun
saman jutun URL:ksi.

TÄRKEÄ: päätä uutuutta HAVAINNON, ei URL:n perusteella. Samalla verkkosivulla voi olla
usean merkittävän henkilön erillisiä kannanottoja, ja ne voivat olla eri havaintoja.
Toisaalta sama henkilön kannanotto voi löytyä myöhemmin paremmalla suoralla URL:lla,
eri otsikolla tai jaettuna toisessa paikassa eikä silloin ole uusi havainto.

Käytä historiaa näin:
- history_action=UPDATE_EXISTING, jos löydös on sisällöllisesti sama jo tunnettu
  kannanotto/julkaisu ja uusi löytö lähinnä vahvistaa URL:n, päivämäärän, tittelin,
  alkuperäislähteen tai muun metadatan.
- history_match_id: anna täsmälleen historiassa olevan havainnon id.
- history_match_reason_fi: kerro lyhyesti miksi kyse on samasta havainnosta.
- history_action=NEW vain kun kyseessä on aidosti uusi julkaisu tai uusi erillinen
  kannanotto. Sama henkilö voi myöhemmin julkaista uuden kannanoton; älä yhdistä niitä
  vain henkilön nimen perusteella.
- history_action=NEW_SYNDICATION, kun kyse on jo tunnetun uutistoimistotekstin uudesta
  jatkojulkaisusta.

Esimerkki: jos historiassa on "Éric Scherer / entinen AFP:n strategiajohtaja" ilman
varmennettua LinkedIn-linkkiä ja löydät hänen saman STT-kannanottonsa suoralla
LinkedIn-URL:lla, se on UPDATE_EXISTING, ei NEW.

Palauta tiivistelmät ja perustelut suomeksi. Otsikko säilytetään alkuperäiskielellä ja
title_fi on suomenkielinen käännös. Älä käytä pitkiä suoria lainauksia.
""".strip()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_url(url):
    try:
        p = urlparse(url.strip())
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ref"}]
        path = re.sub(r"/+$", "", p.path) or "/"
        return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), path, "", urlencode(query), ""))
    except Exception:
        return url


def domain_of(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def valid_http_url(url):
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def is_finnish_domain(domain):
    return domain.endswith(".fi") or any(domain == d or domain.endswith("." + d) for d in FINNISH_DOMAINS)


def stable_id(url):
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def normalize_text(s):
    s = (s or "").lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[^\w\såäöæøüéáíóúßа-яё]", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def title_similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def source_urls(response):
    """Collect URLs that actually appeared in web-search source metadata/citations."""
    try:
        data = response.model_dump()
    except Exception:
        return set()
    found = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "url" and isinstance(v, str) and valid_http_url(v):
                    found.add(normalize_url(v))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data.get("output", []))
    return found


def compact_history(articles, limit=160):
    rows = []
    for a in articles[:limit]:
        rows.append({
            "id": a.get("id"),
            "date": a.get("date_note") or a.get("published_at"),
            "publisher": a.get("publisher"),
            "author": a.get("author"),
            "author_role": a.get("author_role"),
            "platform": a.get("platform"),
            "type": a.get("type"),
            "match": a.get("match_class"),
            "title": a.get("title"),
            "summary_fi": a.get("summary_fi"),
            "reason_fi": a.get("reason_fi"),
            "url": a.get("url"),
            "link_verified": a.get("link_verified"),
            "link_status": a.get("link_status"),
            "cluster_id": a.get("cluster_id"),
        })
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def build_prompt(mode, articles):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if mode == "deep":
        scope = """
TEE PERUSTEELLINEN PÄIVITTÄINEN SWEEP.
- Hae aktiivisesti useilla kielillä Euroopasta ja muualta maailmasta.
- Tarkista uutiset, uutistoimistot, media-alan julkaisut, järjestöt ja julkisesti
  indeksoituvat LinkedIn-, X-, Bluesky- ja muut somepostaukset.
- Etsi sekä viime päivien uudet osumat että mahdolliset aiemmin väliin jääneet osumat
  30.9.2026 jälkeen. Palauta vain osumat, joita tunnetussa historiassa ei vielä ole.
- Tee myös temaattisia hakuja ilman STT-sanaa: national news agency closure/funding,
  original journalism infrastructure, media pluralism, resilience, information
  security, disinformation + Finland/Finnish/context. Hyväksy tällainen osuma vain,
  jos yhteys tähän STT-tapaukseen voidaan perustella lähteillä.
- Painota merkittäviä uusia kannanottajia ja uusia maita.
""".strip()
    else:
        scope = """
TEE NOPEA SEURANTAKIERROS.
- Keskity noin viimeiseen 36 tuntiin.
- Etsi uudet suorat STT-osumat, merkittävät uutis-/järjestökannanotot ja julkiset
  somepostaukset sekä vahvat epäsuorat osumat.
- Tee muutama monikielinen ja temaattinen haku; älä käytä aikaa jo tunnettujen
  syndikointien uudelleen löytämiseen.
""".strip()

    return f"""
Nykyhetki: {now}

{EVENT_CARD}

{WATCHLIST}

{scope}

LUOKITTELU
- CONFIRMED: lähde mainitsee STT:n tai yhteys on muuten lähteen perusteella yksiselitteinen.
- STRONG_MATCH: STT:tä ei välttämättä nimetä, mutta lähteissä on vahva ja selitettävä
  yhteys juuri tähän tapaukseen.
- POSSIBLE_MATCH: vaikutusvaltainen/relevantti lähde ja kiinnostava kontekstiyhteys,
  mutta ihmisen pitää vielä tarkistaa tulkinta. Tällaisia saa palauttaa vain, jos
  konkreettinen yhteys on olemassa — ei pelkkää temaattista samankaltaisuutta.

TÄRKEYS
5 = erittäin merkittävä kansainvälinen/nationaalinen media, uutistoimisto, EU-tason
päättäjä, uutistoimiston ylin johto tai muuten poikkeuksellisen vaikutusvaltainen taho.
4 = suuri valtakunnallinen media/organisaatio tai selvästi merkittävä johtohenkilö.
3 = relevantti media-alan julkaisu, järjestö tai asiantuntija.
2 = pieni mutta relevantti media/taho.
1 = aggregaattori tai heikkolaatuinen lähde.

Tunnettu historia:
{compact_history(articles)}

Vertaa jokaista löytöä historiaan SEMANTTISESTI. Älä päättele uutuutta vain URL:sta.
Jos sama jo tunnettu kannanotto löytyy nyt paremmalla suoralla lähteellä, palauta se
UPDATE_EXISTING-toimintona ja anna history_match_id. Jos samalla sivulla on uusi,
historiasta puuttuva merkittävän henkilön kommentti, se voi olla oma NEW-havaintonsa.

Palauta uusien löytöjen lisäksi vain sellaiset UPDATE_EXISTING-havainnot, joissa uusi
lähde oikeasti parantaa tai varmistaa historiatietoa. Jos mitään uutta tai rikastettavaa
ei ole, items on tyhjä taulukko.
""".strip()


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return None


def find_existing_cluster(articles, same_as_url):
    if not same_as_url:
        return None
    n = normalize_url(same_as_url)
    for a in articles:
        if a.get("url") and normalize_url(a["url"]) == n:
            return a.get("cluster_id") or a.get("id")
    return None


def make_cluster_id(item):
    base = item.get("title") or item.get("publisher") or item.get("url")
    return "agent-" + hashlib.sha1(normalize_text(base).encode("utf-8")).hexdigest()[:12]


def source_match(url, sources):
    n = normalize_url(url)
    if n in sources:
        return True, True
    dom = domain_of(url)
    if dom and any(domain_of(s) == dom for s in sources):
        return True, False
    return False, False



def fold_identity_text(value):
    value = (value or "").strip()
    value = re.sub(r"^(linkedin|x|bluesky|mastodon)\s*/\s*", "", value, flags=re.I)
    # Acronyms in parentheses should not make the same organisation look different:
    # "European Federation of Journalists (EFJ)" == "European Federation of Journalists".
    value = re.sub(r"\s*\([A-ZÅÄÖ0-9.-]{2,12}\)\s*$", "", value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return normalize_text(value)


def actor_key(item):
    """Stable-ish identity for a person/organisation behind one observation."""
    raw = (item.get("author") or item.get("publisher") or "").strip()
    words = fold_identity_text(raw).split()
    # Person names: middle names vary a lot across sources. First + last is useful.
    if item.get("author") and len(words) >= 2:
        return f"{words[0]} {words[-1]}"
    return " ".join(words)


def is_weak_or_indirect_link(article):
    url = (article.get("url") or "").strip()
    status = article.get("link_status")
    if not url or article.get("link_verified") is False:
        return True
    if status in {"not_verified", "indirect_or_profile"}:
        return True
    p = urlparse(url) if url else None
    if p and p.netloc.lower().endswith("linkedin.com") and p.path in {"", "/"}:
        return True
    return False


def find_article_by_id(articles, article_id):
    if not article_id:
        return None
    for a in articles:
        if a.get("id") == article_id:
            return a
    return None


def same_observation(existing, item):
    """
    Conservative deterministic check. The model makes the main semantic decision;
    this catches obvious same-actor/same-post cases and URL duplicates.
    """
    ek = actor_key(existing)
    ik = actor_key(item)
    same_actor = bool(ek and ik and ek == ik)

    eu = normalize_url(existing.get("url") or "") if existing.get("url") else ""
    iu = normalize_url(item.get("url") or "") if item.get("url") else ""
    if eu and iu and eu == iu and same_actor:
        return True

    if same_actor:
        sim = title_similarity(existing.get("title"), item.get("title"))
        if sim >= 0.82:
            return True

        # Seed backfill rows sometimes had only a person/profile and a Finnish
        # summary. If that row was not link-verified, a newly found direct post by
        # the same actor is overwhelmingly likely to be the missing source.
        if existing.get("seed") and is_weak_or_indirect_link(existing):
            return True

    return False


def find_deterministic_history_match(item, articles):
    for a in articles:
        if same_observation(a, item):
            return a
    return None


def merge_observation(existing, raw, exact_source=True, note=None):
    """Enrich a known observation without turning it into a false 'new' hit."""
    changed = False
    old_url = existing.get("url")
    new_url = normalize_url((raw.get("url") or "").strip()) if raw.get("url") else None

    def set_if_better(key, value, overwrite=False):
        nonlocal changed
        if value in (None, "", []):
            return
        if overwrite or existing.get(key) in (None, "", []):
            if existing.get(key) != value:
                existing[key] = value
                changed = True

    # Replace missing/profile/indirect URLs with a direct web-search-supported source.
    if new_url and exact_source:
        if not old_url or is_weak_or_indirect_link(existing):
            if old_url and normalize_url(old_url) != new_url:
                alts = existing.setdefault("alternate_urls", [])
                if old_url not in alts:
                    alts.append(old_url)
            if existing.get("url") != new_url:
                existing["url"] = new_url
                existing["domain"] = raw.get("domain") or domain_of(new_url)
                existing["link_verified"] = True
                existing["link_status"] = "verified"
                changed = True
        elif normalize_url(old_url) != new_url:
            alts = existing.setdefault("alternate_urls", [])
            if new_url not in alts:
                alts.append(new_url)
                changed = True

    # Prefer the actual publication/post title over a placeholder actor label.
    current_title = existing.get("title") or ""
    new_title = raw.get("title") or ""
    placeholder = (
        "/" in current_title
        or normalize_text(current_title) == normalize_text(existing.get("publisher"))
        or normalize_text(current_title) == normalize_text(existing.get("author"))
    )
    if new_title and placeholder and normalize_text(new_title) != normalize_text(current_title):
        existing.setdefault("history_title", current_title)
        existing["title"] = new_title
        changed = True

    # A newly verified exact date can replace an approximate seed date.
    parsed = parse_date(raw.get("published_at"))
    if parsed and (existing.get("date_note") or not existing.get("published_at")):
        if existing.get("published_at") != parsed:
            existing["published_at"] = parsed
            changed = True
        if existing.get("date_note"):
            existing.setdefault("history_date_note", existing.get("date_note"))
            existing["date_note"] = None
            changed = True

    # These enrichments are useful even when the old seed row already existed.
    set_if_better("title_fi", raw.get("title_fi"))
    set_if_better("author", raw.get("author"))
    set_if_better("author_role", raw.get("author_role"))
    set_if_better("agency", raw.get("agency"))
    set_if_better("platform", raw.get("platform"))
    set_if_better("country_code", raw.get("country_code"))
    set_if_better("match_class", raw.get("match_class"))
    set_if_better("direct_stt_reference", raw.get("direct_stt_reference"))
    set_if_better("confidence", raw.get("confidence"))

    if raw.get("importance"):
        try:
            imp = max(int(existing.get("importance") or 1), int(raw.get("importance")))
            if existing.get("importance") != imp:
                existing["importance"] = imp
                changed = True
        except Exception:
            pass

    # Agent summaries are usually more precise than the old backfill wording.
    if raw.get("summary_fi") and raw.get("summary_fi") != existing.get("summary_fi"):
        if existing.get("summary_fi"):
            existing.setdefault("history_summary_fi", existing.get("summary_fi"))
        existing["summary_fi"] = raw.get("summary_fi")
        changed = True
    if raw.get("reason_fi") and raw.get("reason_fi") != existing.get("reason_fi"):
        existing["reason_fi"] = raw.get("reason_fi")
        changed = True

    if changed:
        existing["last_enriched_at"] = now_iso()
        existing["discovered_by"] = existing.get("discovered_by") or "seed_backfill"
        existing["history_update_note"] = note or raw.get("history_match_reason_fi") or "Agentti vahvisti/rikasti aiemman havainnon."
    return changed


def reconcile_existing_history(articles):
    """
    One-time-safe cleanup for duplicates created by the first agent run.
    - same URL is only a duplicate when the actor/organisation is also the same;
      one NMC page may legitimately contain separate NMC, Giboi, Guzenina observations.
    - old unverified seed actor + newly found direct agent post -> enrich seed.
    - for the initial migration only, same seed actor and an agent item first seen
      by 12 Oct 2026 are merged even when the seed link was already indirect/shared.
      Future genuinely new posts by that person are not affected.
    """
    kept = []
    merged_count = 0
    migration_cutoff = datetime(2026, 10, 12, tzinfo=timezone.utc)

    for item in articles:
        target = None
        for existing in kept:
            if same_observation(existing, item):
                target = existing
                break

            # Cleanup of the specific first agent pass: same actor, seed vs agent,
            # discovered before migration cutoff. This catches e.g. Giboi while
            # leaving future separate posts alone.
            if existing.get("seed") and not item.get("seed"):
                ek, ik = actor_key(existing), actor_key(item)
                if ek and ik and ek == ik:
                    try:
                        seen = datetime.fromisoformat((item.get("first_seen") or "").replace("Z", "+00:00"))
                    except Exception:
                        seen = None
                    if seen and seen <= migration_cutoff:
                        target = existing
                        break

        if target:
            merge_observation(
                target,
                item,
                exact_source=bool(item.get("link_verified", True)),
                note="Ensimmäisen agenttiajon semanttinen duplikaatti yhdistettiin aiempaan havaintoon."
            )
            merged_count += 1
        else:
            kept.append(item)

    return kept, merged_count


def actions_summary(mode, result, added, updated, rejected, cleanup_merged):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## STT World Watch – AI agent",
        "",
        f"- Mode: **{mode}**",
        f"- Agent candidates: **{len(result.get('items', []))}**",
        f"- Genuinely new observations: **{len(added)}**",
        f"- Existing observations enriched: **{len(updated)}**",
        f"- Old duplicate rows merged in cleanup: **{cleanup_merged}**",
        f"- Rejected/unverifiable candidates: **{len(rejected)}**",
        f"- Run time: **{now_iso()}**",
        "",
        "### Agent summary",
        result.get("run_summary_fi", "–"),
    ]
    if added:
        lines += ["", "### Added as genuinely new"]
        for a in added:
            lines.append(f"- **{a['match_class']} · {a['importance']}/5** — {a['publisher']}: {a['title']}")
    if updated:
        lines += ["", "### Enriched existing observations"]
        for a in updated[:20]:
            lines.append(f"- **UPDATED** — {a.get('publisher')}: {a.get('title')}")
    if rejected:
        lines += ["", "### Skipped"]
        lines.extend(f"- {x}" for x in rejected[:15])
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["monitor", "deep"], default="monitor")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY puuttuu GitHub Secretsistä.", file=sys.stderr)
        sys.exit(2)

    articles = load_json(ARTICLES_PATH, [])
    if not isinstance(articles, list):
        print("articles.json ei ole taulukko.", file=sys.stderr)
        sys.exit(2)

    # First clean the duplicate rows that the very first semantic-agent pass may
    # have added before observation-level deduplication existed.
    articles, cleanup_merged = reconcile_existing_history(articles)

    model = os.environ.get("OPENAI_MODEL", "gpt-6.1-sol")
    effort = "medium" if args.mode == "deep" else "low"
    context_size = "high" if args.mode == "deep" else "medium"

    client = OpenAI()
    print(f"Running semantic STT World Watch: mode={args.mode}, model={model}")

    response = client.responses.create(
        model=model,
        reasoning={"effort": effort},
        tools=[{"type": "web_search", "search_context_size": context_size}],
        tool_choice="auto",
        include=["web_search_call.action.sources"],
        instructions=SYSTEM,
        input=build_prompt(args.mode, articles),
        text={
            "format": {
                "type": "json_schema",
                "name": "stt_world_watch_results",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )

    try:
        result = json.loads(response.output_text)
    except Exception as e:
        print("Agentin JSON-vastausta ei voitu lukea:", e, file=sys.stderr)
        print(response.output_text[:4000], file=sys.stderr)
        sys.exit(3)

    sources = source_urls(response)
    print(f"Web source URLs available for validation: {len(sources)}")

    added = []
    updated = []
    rejected = []
    seen_new_observations = set()

    for raw in result.get("items", []):
        url = (raw.get("url") or "").strip()
        if not valid_http_url(url):
            rejected.append(f"invalid URL: {raw.get('title','?')}")
            continue

        dom = domain_of(url)
        if is_finnish_domain(dom):
            rejected.append(f"Finnish source skipped: {dom}")
            continue

        has_source, exact_source = source_match(url, sources)
        if not has_source:
            rejected.append(
                f"source not found in web-search evidence: "
                f"{raw.get('publisher')} — {raw.get('title')}"
            )
            continue

        raw["url"] = normalize_url(url)
        raw["domain"] = raw.get("domain") or dom

        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        if raw.get("match_class") == "POSSIBLE_MATCH" and confidence < 0.55:
            rejected.append(f"weak possible match ({confidence:.2f}): {raw.get('title')}")
            continue

        # The model can explicitly identify a history row. If it does, enrich it.
        history_action = raw.get("history_action") or "NEW"
        model_match = find_article_by_id(articles, raw.get("history_match_id"))

        # Deterministic fallback catches obvious same-post cases.
        deterministic_match = find_deterministic_history_match(raw, articles)

        target = None
        if history_action == "UPDATE_EXISTING" and model_match:
            target = model_match
        elif deterministic_match:
            target = deterministic_match

        if target:
            if merge_observation(
                target,
                raw,
                exact_source=exact_source,
                note=raw.get("history_match_reason_fi")
            ):
                if target not in updated:
                    updated.append(target)
            continue

        # NEW_SYNDICATION is new as a publication, but belongs to an existing cluster.
        published = parse_date(raw.get("published_at"))
        cluster_id = find_existing_cluster(articles, raw.get("same_as_url")) or make_cluster_id(raw)
        country = (raw.get("country") or "Tuntematon").strip()
        cc = raw.get("country_code") or COUNTRY_CODES.get(country)
        importance = max(1, min(5, int(raw.get("importance") or 2)))

        # Prevent an exact same actor+URL from being added twice in this one run.
        observation_key = (actor_key(raw), normalize_url(raw["url"]), normalize_text(raw.get("title")))
        if observation_key in seen_new_observations:
            continue
        seen_new_observations.add(observation_key)

        article = {
            "id": stable_id(raw["url"] + "|" + (actor_key(raw) or normalize_text(raw.get("title")))),
            "cluster_id": cluster_id,
            "title": raw.get("title") or raw.get("publisher") or dom,
            "title_fi": raw.get("title_fi"),
            "url": raw["url"],
            "domain": raw.get("domain") or dom,
            "publisher": raw.get("publisher") or dom,
            "country": country,
            "country_code": cc,
            "published_at": published or now_iso(),
            "date_note": raw.get("date_note") if not published else None,
            "author": raw.get("author"),
            "author_role": raw.get("author_role"),
            "agency": raw.get("agency"),
            "platform": raw.get("platform"),
            "type": raw.get("type") or "ORIGINAL",
            "match_class": raw.get("match_class") or "CONFIRMED",
            "direct_stt_reference": bool(raw.get("direct_stt_reference")),
            "confidence": confidence,
            "importance": importance,
            "summary_fi": raw.get("summary_fi") or "",
            "reason_fi": raw.get("reason_fi") or "",
            "first_seen": now_iso(),
            "seed": False,
            "link_verified": bool(exact_source),
            "discovered_by": "openai_web_search_agent",
            "history_action": history_action,
        }
        added.append(article)

    actions_summary(args.mode, result, added, updated, rejected, cleanup_merged)

    changed = bool(added or updated or cleanup_merged)
    if not changed:
        print("No genuinely new or enrichable items. Repository data left unchanged.")
        if rejected:
            print("Skipped:")
            for x in rejected[:20]:
                print("-", x)
        return

    merged = articles + added
    merged.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    ARTICLES_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    status = load_json(STATUS_PATH, {})
    status.update({
        "last_data_update": now_iso(),
        "last_success": now_iso(),
        "new_count": len(added),
        "updated_count": len(updated),
        "cleanup_merged": cleanup_merged,
        "source_count": len(sources),
        "error": None,
        "agent_mode": args.mode,
        "agent_summary_fi": result.get("run_summary_fi"),
        "agent_search_notes_fi": result.get("search_notes_fi"),
    })
    STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(
        f"Added {len(added)} genuinely new observations; "
        f"enriched {len(updated)} existing observations; "
        f"cleanup merged {cleanup_merged} old duplicate rows."
    )
    for a in added:
        print(f"+ {a['match_class']} {a['importance']}/5 {a['publisher']}: {a['title']}")
    for a in updated:
        print(f"~ UPDATED {a.get('publisher')}: {a.get('title')}")


if __name__ == "__main__":
    main()
