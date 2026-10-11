#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
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
                    "same_as_url": {"type": ["string", "null"]}
                },
                "required": [
                    "title", "title_fi", "url", "publisher", "domain", "country",
                    "country_code", "published_at", "date_note", "author",
                    "author_role", "agency", "platform", "type", "match_class",
                    "direct_stt_reference", "confidence", "importance", "summary_fi",
                    "reason_fi", "same_as_url"
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
saman jutun URL:ksi. Älä palauta jo tunnettua URL:ia uudelleen.

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
            "date": a.get("date_note") or a.get("published_at"),
            "publisher": a.get("publisher"),
            "author": a.get("author"),
            "type": a.get("type"),
            "match": a.get("match_class"),
            "title": a.get("title"),
            "url": a.get("url"),
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

Tunnettu historia (älä palauta samoja URL:eja uudelleen; uudet syndikointijulkaisut
saa palauttaa same_as_url-kentän avulla):
{compact_history(articles)}

Palauta vain uudet löydöt. Jos mitään uutta ei ole, items on tyhjä taulukko.
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


def candidate_is_duplicate(item, articles):
    nurl = normalize_url(item["url"])
    for a in articles:
        if a.get("url") and normalize_url(a["url"]) == nurl:
            return True
    # Same publisher/author + essentially same title is almost certainly duplicate.
    for a in articles[:200]:
        same_actor = (normalize_text(a.get("publisher")) == normalize_text(item.get("publisher")) or
                      (item.get("author") and normalize_text(a.get("author")) == normalize_text(item.get("author"))))
        if same_actor and title_similarity(a.get("title"), item.get("title")) >= 0.95:
            return True
    return False


def actions_summary(mode, result, accepted, rejected):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## STT World Watch – AI agent",
        "",
        f"- Mode: **{mode}**",
        f"- Agent candidates: **{len(result.get('items', []))}**",
        f"- New accepted items: **{len(accepted)}**",
        f"- Rejected/unverifiable candidates: **{len(rejected)}**",
        f"- Run time: **{now_iso()}**",
        "",
        "### Agent summary",
        result.get("run_summary_fi", "–"),
    ]
    if accepted:
        lines += ["", "### Added"]
        for a in accepted:
            lines.append(f"- **{a['match_class']} · {a['importance']}/5** — {a['publisher']}: {a['title']}")
    if rejected:
        lines += ["", "### Skipped"]
        lines.extend(f"- {x}" for x in rejected[:12])
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

    accepted = []
    rejected = []
    seen_new = set()

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
            rejected.append(f"source not found in web-search evidence: {raw.get('publisher')} — {raw.get('title')}")
            continue

        raw["url"] = normalize_url(url)
        if candidate_is_duplicate(raw, articles) or raw["url"] in seen_new:
            continue
        seen_new.add(raw["url"])

        published = parse_date(raw.get("published_at"))
        cluster_id = find_existing_cluster(articles, raw.get("same_as_url")) or make_cluster_id(raw)
        country = (raw.get("country") or "Tuntematon").strip()
        cc = raw.get("country_code") or COUNTRY_CODES.get(country)
        importance = max(1, min(5, int(raw.get("importance") or 2)))
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))

        # POSSIBLE_MATCH is kept for human review, but it must have meaningful confidence.
        if raw.get("match_class") == "POSSIBLE_MATCH" and confidence < 0.55:
            rejected.append(f"weak possible match ({confidence:.2f}): {raw.get('title')}")
            continue

        article = {
            "id": stable_id(raw["url"]),
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
        }
        accepted.append(article)

    actions_summary(args.mode, result, accepted, rejected)

    if not accepted:
        print("No new verified items. Repository data left unchanged.")
        if rejected:
            print("Skipped:")
            for x in rejected[:20]:
                print("-", x)
        return

    merged = articles + accepted
    merged.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    ARTICLES_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    status = load_json(STATUS_PATH, {})
    status.update({
        "last_data_update": now_iso(),
        "last_success": now_iso(),
        "new_count": len(accepted),
        "source_count": len(sources),
        "error": None,
        "agent_mode": args.mode,
        "agent_summary_fi": result.get("run_summary_fi"),
        "agent_search_notes_fi": result.get("search_notes_fi"),
    })
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Added {len(accepted)} new items.")
    for a in accepted:
        print(f"- {a['match_class']} {a['importance']}/5 {a['publisher']}: {a['title']}")


if __name__ == "__main__":
    main()
