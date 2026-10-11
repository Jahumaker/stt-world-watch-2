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

EVENT_START = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
BASELINE_SOURCE_ROWS = set(range(1, 44))

# Authoritative baseline from the 30.9.–10.10.2026 monitoring report.
# This is intentionally embedded so the workflow can restore any missing
# historical observations before deciding what is "new".
BASELINE_HISTORY = json.loads(r"""[{"id":"hist-38-2bdecbb0","cluster_id":"hist-38","title":"Clive Marshall / entinen PA Media Group","title_fi":null,"url":"https://uk.linkedin.com/in/clive-marshall-65563b95","domain":"uk.linkedin.com","publisher":"LinkedIn / Clive Marshall","country":"Britannia","country_code":"GB","published_at":"2026-10-08T12:00:00+00:00","date_note":"Arviolta 7.–9.10.","author":"Clive Marshall","agency":null,"type":"COMMENT","importance":4,"summary_fi":"PA Median ja AAP:n entinen johtaja vaatii laajaa kampanjaa STT:n pelastamiseksi. Hänen mukaansa lakkautus uhkaisi riippumatonta uutisvälitystä ja pieniä medioita. Henkilökohtainen kommentti.","first_seen":"2026-10-08T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"indirect_or_profile","source_row":38},{"id":"hist-39-f66d42a7","cluster_id":"hist-39","title":"Aimilios Perdikaris / EANA","title_fi":null,"url":null,"domain":"","publisher":"LinkedIn / Aimilios Perdikaris","country":"Kreikka","country_code":"GR","published_at":"2026-10-08T12:00:00+00:00","date_note":"Arviolta 7.–8.10.","author":"Aimilios Perdikaris","agency":null,"type":"COMMENT","importance":3,"summary_fi":"EANAn hallituksen jäsen kertoi aiemman seurannan mukaan koordinoiduista toimista STT:n tukemiseksi. Alkuperäisen LinkedIn-julkaisun päivää ja osoitetta ei vahvistettu.","first_seen":"2026-10-08T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"not_verified","source_row":39},{"id":"hist-40-9fcc71c7","cluster_id":"hist-40","title":"Éric Scherer / entinen AFP:n strategiajohtaja","title_fi":null,"url":"https://www.linkedin.com/","domain":"linkedin.com","publisher":"LinkedIn / Éric Scherer","country":"Ranska","country_code":"FR","published_at":"2026-10-08T12:00:00+00:00","date_note":"Arviolta 7.–8.10.","author":"Éric Scherer","agency":null,"type":"COMMENT","importance":4,"summary_fi":"Scherer rinnastaa STT:n lakkautusuhan Suomen informaatioturvallisuuden heikentämiseen: F-35-hävittäjiin investoiva Venäjän rajanaapuri ei saisi luopua luotettavasta uutisinfrastruktuurista. Hän arvostelee Sanoman päätöstä ja valtion tukiratkaisua.","first_seen":"2026-10-08T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"indirect_or_profile","source_row":40},{"id":"hist-31-7d644983","cluster_id":"hist-31","title":"Media.ba / Mediacentar Sarajevo","title_fi":null,"url":null,"domain":"","publisher":"Media.ba / Mediacentar Sarajevo","country":"Bosnia ja Hertsegovina","country_code":"BA","published_at":"2026-10-06T12:00:00+00:00","date_note":"6.10.","author":null,"agency":null,"type":"FOLLOW-UP","importance":3,"summary_fi":"Media-alan erikoisjulkaisu käsittelee STT:n mahdollista katoamista ja EFJ:n huolta Euroopan uutistoimistokentästä.","first_seen":"2026-10-06T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"not_verified","source_row":31},{"id":"hist-36-9e0d5e34","cluster_id":"hist-36","title":"Public Interest Journalism Initiative (PIJI)","title_fi":null,"url":"https://piji.com.au/newsletters/october-2026-newsletter/","domain":"piji.com.au","publisher":"Public Interest Journalism Initiative (PIJI)","country":"Australia","country_code":"AU","published_at":"2026-10-06T12:00:00+00:00","date_note":"6.10.","author":null,"agency":null,"type":"FOLLOW-UP","importance":3,"summary_fi":"Lokakuun uutiskirje nostaa STT:n kansainväliseksi media-alan huolenaiheeksi ja painottaa erityisesti pienten medioiden riippuvuutta uutistoimistopalveluista.","first_seen":"2026-10-06T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":36},{"id":"hist-34-6b2907e9","cluster_id":"hist-34","title":"Udruženje novinara Srbije (UNS)","title_fi":null,"url":"https://www.uns.org.rs/sr/desk/vesti-iz-medija/192006/finska-novinska-agencija-medju-najstarijim-na-svetu-pred-gasenjem.html","domain":"uns.org.rs","publisher":"Udruženje novinara Srbije (UNS)","country":"Serbia","country_code":"RS","published_at":"2026-10-06T10:01:00+00:00","date_note":"6.10. klo 10.01","author":null,"agency":null,"type":"FOLLOW-UP","importance":3,"summary_fi":"Serbian journalistiyhdistyksen julkaisu, joka korostaa EFJ:n huolta ja kansallisen uutistoimiston merkitystä.","first_seen":"2026-10-06T10:01:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":34},{"id":"hist-37-0a998c8e","cluster_id":"hist-37","title":"Sebastian Raabe / dpa","title_fi":null,"url":"https://de.linkedin.com/posts/sebastianraabe_wir-reden-viel-dar%C3%BCber-wie-ki-nachrichten-activity-7512790118051500032-lQEs","domain":"de.linkedin.com","publisher":"LinkedIn / Sebastian Raabe","country":"Saksa","country_code":"DE","published_at":"2026-10-05T12:00:00+00:00","date_note":"5.10.","author":"Sebastian Raabe","agency":null,"type":"COMMENT","importance":4,"summary_fi":"dpa:n johtohenkilön henkilökohtainen kirjoitus vertaa uutistoimistoja välttämättömään infrastruktuuriin: kuka maksaa alkuperäisen, tarkistetun uutisen tuottamisesta? Ei dpa:n virallinen lausunto.","first_seen":"2026-10-05T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":37},{"id":"hist-16-9b171160","cluster_id":"hist-16","title":"Hans Vandendriessche / Belga","title_fi":null,"url":null,"domain":"","publisher":"Belga","country":"Belgia","country_code":"BE","published_at":"2026-10-03T12:00:00+00:00","date_note":"Lokakuun alku","author":"Hans Vandendriessche","agency":null,"type":"COMMENT","importance":4,"summary_fi":"Belgan päätoimittajan henkilökohtainen kannanotto: tekoäly ei korvaa toimittajien alkuperäistä tiedonhankintaa; riippumaton uutistoimisto on tärkeä myös informaatioturvallisuudelle.","first_seen":"2026-10-03T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"not_verified","source_row":16},{"id":"hist-35-25887c53","cluster_id":"lusa-stt-closure","title":"Executive Digest / Lusa","title_fi":null,"url":"https://executivedigest.sapo.pt/","domain":"executivedigest.sapo.pt","publisher":"Executive Digest","country":"Portugali","country_code":"PT","published_at":"2026-10-03T12:00:00+00:00","date_note":"3.10.","author":null,"agency":"Lusa","type":"SYNDICATED","importance":3,"summary_fi":"Lusan uutistoimistoaineisto: tappiot, Sanoman asiakkuuden päättyminen, omistajien ratkaisuyritykset ja EFJ:n huoli.","first_seen":"2026-10-03T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"indirect_or_profile","source_row":35},{"id":"hist-32-f03b60f7","cluster_id":"beta-stt-closure","title":"Beta","title_fi":null,"url":"https://beta.rs/content/253102-finska-novinska-agencija-medu-najstarijim-na-svetu-pred-gasenjem","domain":"beta.rs","publisher":"Beta","country":"Serbia","country_code":"RS","published_at":"2026-10-02T13:15:00+00:00","date_note":"2.10. klo 13.15","author":null,"agency":"Beta","type":"AGENCY","importance":4,"summary_fi":"Serbian uutistoimiston oma uutinen STT:n lakkautusuhasta.","first_seen":"2026-10-02T13:15:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":32},{"id":"hist-30-37b991cd","cluster_id":"fena-stt-closure","title":"Bosnainfo","title_fi":null,"url":"https://bosnainfo.ba/svijet/finska-novinska-agencija-stt-pred-mogucim-gasenjem-nakon-gotovo-140-godina-rada/","domain":"bosnainfo.ba","publisher":"Bosnainfo","country":"Bosnia ja Hertsegovina","country_code":"BA","published_at":"2026-10-02T12:00:00+00:00","date_note":"2.10.","author":null,"agency":"FENA","type":"SYNDICATED","importance":2,"summary_fi":"klo 21FENA-aineiston jatkojulkaisu.","first_seen":"2026-10-02T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":30},{"id":"hist-33-240dc288","cluster_id":"beta-stt-closure","title":"Serbian News Media","title_fi":null,"url":"https://snm.rs/finnish-news-agency-among-the-oldest-in-the-world-facing-closure/","domain":"snm.rs","publisher":"Serbian News Media","country":"Serbia","country_code":"RS","published_at":"2026-10-02T12:00:00+00:00","date_note":"2.–3.10.","author":null,"agency":"Beta","type":"SYNDICATED","importance":2,"summary_fi":"Beta-aineiston englanninkielinen jatkojulkaisu.","first_seen":"2026-10-02T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":33},{"id":"hist-42-749d3c4f","cluster_id":"nmc-eana-stt","title":"News Media Coalition (NMC)","title_fi":null,"url":"https://www.newsmediacoalition.org/why-the-death-throes-of-finlands-national-news-agency-is-a-wake-up-call-for-governments-seeking-to-combat-disinformation/","domain":"newsmediacoalition.org","publisher":"News Media Coalition (NMC)","country":"Kansainväliset järjestöt","country_code":null,"published_at":"2026-10-02T12:00:00+00:00","date_note":"2.10.","author":null,"agency":null,"type":"FOLLOW-UP","importance":4,"summary_fi":"NMC:n analyysi: disinformaatiota torjuvat valtiot eivät saa päästää alkuperäisen uutistyön infrastruktuuria rapautumaan. Kirjoitus kytkee STT:n 13.10. Brysselissä pidettävään tilaisuuteen.","first_seen":"2026-10-02T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":42},{"id":"hist-43-d3eb69cf","cluster_id":"nmc-eana-stt","title":"European Alliance of News Agencies (EANA) / Alexandru Giboi","title_fi":null,"url":"https://www.newsmediacoalition.org/why-the-death-throes-of-finlands-national-news-agency-is-a-wake-up-call-for-governments-seeking-to-combat-disinformation/","domain":"newsmediacoalition.org","publisher":"News Media Coalition / EANA","country":"Kansainväliset järjestöt","country_code":null,"published_at":"2026-10-02T12:00:00+00:00","date_note":"2.10.","author":"Alexandru Giboi","agency":null,"type":"COMMENT","importance":4,"summary_fi":"EANAn pääsihteerin STT:tä tukeva kannanotto NMC:n artikkelin yhteydessä; ei erillinen uutisjulkaisu.","first_seen":"2026-10-02T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"shared_article","source_row":43},{"id":"hist-29-3b54fbce","cluster_id":"fena-stt-closure","title":"6yka","title_fi":null,"url":"https://6yka.com/svijet/finska-novinska-agencija-stt-pred-mogucim-gasenjem-nakon-gotovo-140-godina-rada/","domain":"6yka.com","publisher":"6yka","country":"Bosnia ja Hertsegovina","country_code":"BA","published_at":"2026-10-02T09:17:00+00:00","date_note":"2.10. klo 9.17","author":null,"agency":"FENA","type":"SYNDICATED","importance":2,"summary_fi":"FENA-aineiston jatkojulkaisu.","first_seen":"2026-10-02T09:17:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":29},{"id":"hist-28-25bcb734","cluster_id":"fena-stt-closure","title":"Federalna.ba","title_fi":null,"url":"https://www.federalna.ba/finska-novinska-agencija-stt-pred-mogucim-gasenjem-nakon-gotovo-140-godina-rada-ro4qt","domain":"federalna.ba","publisher":"Federalna.ba","country":"Bosnia ja Hertsegovina","country_code":"BA","published_at":"2026-10-02T09:15:00+00:00","date_note":"2.10. klo 9.15","author":null,"agency":"FENA","type":"SYNDICATED","importance":2,"summary_fi":"FENA-aineiston jatkojulkaisu.","first_seen":"2026-10-02T09:15:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":28},{"id":"hist-27-8ab83214","cluster_id":"fena-stt-closure","title":"FENA","title_fi":null,"url":"https://test.fena.ba/article/1699402/finska-novinska-agencija-stt-pred-mogucim-gasenjem-nakon-gotovo-140-godina-rada","domain":"test.fena.ba","publisher":"FENA","country":"Bosnia ja Hertsegovina","country_code":"BA","published_at":"2026-10-02T08:02:00+00:00","date_note":"2.10. klo 8.02","author":null,"agency":"FENA","type":"AGENCY","importance":4,"summary_fi":"Maan uutistoimiston alkuperäinen uutinen: STT:n lähes 140-vuotinen toiminta saattaa päättyä; taustalla pitkäaikaiset tappiot.","first_seen":"2026-10-02T08:02:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":27},{"id":"hist-23-02d8214e","cluster_id":"hina-stt-closure","title":"HRT / Hina","title_fi":null,"url":"https://vijesti.hrt.hr/eu/finska-mozda-gubi-svoju-novinsku-agenciju-jednu-od-najstarijih-na-svijetu-12935373","domain":"vijesti.hrt.hr","publisher":"HRT","country":"Kroatia","country_code":"HR","published_at":"2026-10-01T14:58:00+00:00","date_note":"1.10. klo 14.58","author":null,"agency":"Hina","type":"SYNDICATED","importance":4,"summary_fi":"Kroatian yleisradio julkaisi kansallisen uutistoimisto Hinan jutun: Suomi saattaa menettää yhden maailman vanhimmista uutistoimistoista.","first_seen":"2026-10-01T14:58:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":23},{"id":"hist-07-1305fa7d","cluster_id":"hist-07","title":"Journalisten / Johannes Nesser","title_fi":null,"url":"https://www.journalisten.se/nyheter/finska-nyhetsbyran-stt-varslar-alla-journalister-facket-varnar-for-dominoeffekt/","domain":"journalisten.se","publisher":"Journalisten","country":"Ruotsi","country_code":"SE","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":"Johannes Nesser","agency":null,"type":"ORIGINAL","importance":3,"summary_fi":"Oma media-alan uutinen: STT:n journalistisen toiminnan mahdollinen päättyminen ja Journalistiliiton varoitus dominoefektistä suomalaisessa mediassa.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":7},{"id":"hist-08-749758b3","cluster_id":"hist-08","title":"Epoch Times Sverige","title_fi":null,"url":"https://www.epochtimes.se/finska-nyhetsbyran-stt-kan-laggas-ned","domain":"epochtimes.se","publisher":"Epoch Times Sverige","country":"Ruotsi","country_code":"SE","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":2,"summary_fi":"Uutinen STT:n mahdollisesta lakkauttamisesta.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":8},{"id":"hist-09-b768e3d2","cluster_id":"nordic-journalist-unions-stt","title":"Svenska Journalistförbundet","title_fi":null,"url":"https://www.sjf.se/aktuellt/202610/uttalande-fran-de-nordiska-och-estniska-journalistforbunden","domain":"sjf.se","publisher":"Svenska Journalistförbundet","country":"Ruotsi","country_code":"SE","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"COMMENT","importance":3,"summary_fi":"Pohjoismaisten ja Viron journalistiliittojen yhteinen vetoomus STT:n turvaamiseksi: moniarvoisuus, luotettava tieto ja kriisinkestävyys.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":9},{"id":"hist-11-f387d619","cluster_id":"hist-11","title":"Journalisten Norge","title_fi":null,"url":"https://www.journalisten.no/notice/684632","domain":"journalisten.no","publisher":"Journalisten","country":"Norja","country_code":"NO","published_at":"2026-10-01T12:00:00+00:00","date_note":"30.9.–1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":3,"summary_fi":"Media-alan uutinen STT:n kriisitoimista ja uutis- sekä kuvapalvelujen tulevaisuudesta.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":11},{"id":"hist-18-07912c59","cluster_id":"nordic-journalist-unions-stt","title":"Eesti Ajakirjanike Liit","title_fi":null,"url":"https://www.sjf.se/aktuellt/202610/uttalande-fran-de-nordiska-och-estniska-journalistforbunden","domain":"sjf.se","publisher":"Eesti Ajakirjanike Liit","country":"Viro","country_code":"EE","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"COMMENT","importance":3,"summary_fi":"Osallistui Pohjoismaiden ja Viron journalistiliittojen yhteiseen STT-kannanottoon.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"shared_statement_source","source_row":18},{"id":"hist-20-5182ac22","cluster_id":"uanews-stt-restructuring","title":"UA.News (ukrainaksi)","title_fi":null,"url":"https://ua.news/ua/world/stt-u-finliandiyi-mozhe-pripiniti-robotu-cherez-restrukturizatsiiu-yle-news","domain":"ua.news","publisher":"UA.News (ukrainaksi)","country":"Ukraina","country_code":"UA","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":2,"summary_fi":"Yle Newsiin pohjautuva uutinen STT:n toiminnan mahdollisesta päättymisestä.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":20},{"id":"hist-21-85a2ddfc","cluster_id":"uanews-stt-restructuring","title":"UA.News (englanniksi)","title_fi":null,"url":"https://ua.news/en/world/stt-u-finliandiyi-mozhe-pripiniti-robotu-cherez-restrukturizatsiiu-yle-news","domain":"ua.news","publisher":"UA.News (englanniksi)","country":"Ukraina","country_code":"UA","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":2,"summary_fi":"Saman uutisen englanninkielinen versio.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":21},{"id":"hist-24-b3418a0f","cluster_id":"hina-stt-closure","title":"Tportal / Hina","title_fi":null,"url":"https://www.tportal.hr/vijesti/clanak/jednoj-od-najstarijih-novinarskih-agencija-na-svijetu-prijeti-gasenje-finska-vlada-je-pokusala-spasiti-20261001","domain":"tportal.hr","publisher":"Tportal","country":"Kroatia","country_code":"HR","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":"Hina","type":"SYNDICATED","importance":3,"summary_fi":"Hinan aineiston jatkojulkaisu.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":24},{"id":"hist-25-b56281da","cluster_id":"hist-25","title":"Novi list","title_fi":null,"url":"https://www.novilist.hr/novosti/nakon-madarske-i-finska-bi-mogla-ostati-bez-jedne-od-svojih-kljucnih-medijskih-institucija/","domain":"novilist.hr","publisher":"Novi list","country":"Kroatia","country_code":"HR","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":3,"summary_fi":"STT:n kriisiä käsittelevä kroatialainen julkaisu.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":25},{"id":"hist-26-eb401b5e","cluster_id":"hist-26","title":"Jutarnji list","title_fi":null,"url":"https://www.jutarnji.hr/vijesti/svijet/stt-finska-restrukturiranje-moguce-gasenje-sanoma-gubici-15751717","domain":"jutarnji.hr","publisher":"Jutarnji list","country":"Kroatia","country_code":"HR","published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"ORIGINAL","importance":3,"summary_fi":"Uutinen yhden maailman vanhimpiin kuuluvan uutistoimiston lakkautusuhasta.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":26},{"id":"hist-41-1ecb89bf","cluster_id":"hist-41","title":"European Federation of Journalists (EFJ)","title_fi":null,"url":"https://europeanjournalists.org/blog/2026/10/01/finland-news-agency-stt-faces-threats-of-closure/","domain":"europeanjournalists.org","publisher":"European Federation of Journalists (EFJ)","country":"Kansainväliset järjestöt","country_code":null,"published_at":"2026-10-01T12:00:00+00:00","date_note":"1.10.","author":null,"agency":null,"type":"FOLLOW-UP","importance":4,"summary_fi":"EFJ pitää STT:n mahdollista katoamista uhkana mediapluralismille, lehdistönvapaudelle ja alueellisten tiedotusvälineiden tiedonsaannille.","first_seen":"2026-10-01T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":41},{"id":"hist-22-f25a2859","cluster_id":"sta-stt-closure","title":"Dnevnik / STA","title_fi":null,"url":"https://www.dnevnik.si/novice/svet/finski-tiskovni-agenciji-stt-sredi-financnih-tezav-grozi-zaprtje-2831008/","domain":"dnevnik.si","publisher":"Dnevnik","country":"Slovenia","country_code":"SI","published_at":"2026-10-01T10:07:00+00:00","date_note":"1.10. klo 10.07","author":null,"agency":"STA","type":"SYNDICATED","importance":3,"summary_fi":"Slovenian kansallisen uutistoimiston aineisto STT:n talousvaikeuksista, 95 työpaikasta ja mahdollisesta lakkautuksesta.","first_seen":"2026-10-01T10:07:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":22},{"id":"hist-19-697aec63","cluster_id":"hist-19","title":"Delovoi Peterburg","title_fi":null,"url":"https://www.dp.ru/a/2026/09/30/glavnoe-informagentstvo-finljandii","domain":"dp.ru","publisher":"Delovoi Peterburg","country":"Venäjä","country_code":"RU","published_at":"2026-09-30T16:43:00+00:00","date_note":"30.9. klo 16.43","author":null,"agency":null,"type":"ORIGINAL","importance":3,"summary_fi":"Pietarilainen talousmedia kuvaa STT:tä Suomen keskeiseksi uutistoimistoksi ja uutisoi tappioiden vuoksi suunnitellusta alasajosta. Otsikko on suunnitelmaa lopullisempi.","first_seen":"2026-09-30T16:43:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":19},{"id":"hist-01-1ba3b0a8","cluster_id":"tt-nyhetsbyra-i-kris","title":"Svenska Dagbladet / TT","title_fi":null,"url":"https://www.svd.se/a/d4oBbB/nyhetsbyra-i-kris-verksamhet-kan-upphora","domain":"svd.se","publisher":"Svenska Dagbladet","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":4,"summary_fi":"TT:n uutinen STT:n talousvaikeuksista ja mahdollisesta uutis- ja kuvatoiminnan päättymisestä.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":1},{"id":"hist-02-4222061b","cluster_id":"tt-nyhetsbyra-i-kris","title":"Aftonbladet / TT","title_fi":null,"url":"https://www.aftonbladet.se/nyheter/a/GxzgnJ/nyhetsbyra-i-kris-verksamhet-kan-upphora","domain":"aftonbladet.se","publisher":"Aftonbladet","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":4,"summary_fi":"Saman TT-uutisen julkaisu valtakunnallisessa iltapäivälehdessä.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":2},{"id":"hist-03-8f85b6d7","cluster_id":"tt-nyhetsbyra-i-kris","title":"Göteborgs-Posten / TT","title_fi":null,"url":"https://www.gp.se/nyheter/varlden/nyhetsbyra-i-kris-verksamhet-kan-upphora.af3ace1b-a2e8-53e7-8089-6e9c3a4d58a2","domain":"gp.se","publisher":"Göteborgs-Posten","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":4,"summary_fi":"TT:n aineiston jatkojulkaisu.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":3},{"id":"hist-04-e6bb1fc3","cluster_id":"tt-nyhetsbyra-i-kris","title":"TV4 / TT","title_fi":null,"url":"https://www.tv4.se/artikel/tt-260930-finlandnyhetsbyra1-74769eff/nyhetsbyra-i-kris-verksamhet-kan-upphora","domain":"tv4.se","publisher":"TV4","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":4,"summary_fi":"TT:n STT-uutinen televisiokanavan verkkopalvelussa.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":4},{"id":"hist-05-7f58d041","cluster_id":"tt-nyhetsbyra-i-kris","title":"Dagens Media / TT","title_fi":null,"url":"https://www.dagensmedia.se/tidningar-och-tidskrifter/dagspress/nyhetsbyra-i-kris-verksamhet-kan-upphora/","domain":"dagensmedia.se","publisher":"Dagens Media","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":3,"summary_fi":"Media-alan julkaisun levittämä TT-uutinen.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":5},{"id":"hist-06-e4bc1657","cluster_id":"tt-nyhetsbyra-i-kris","title":"Nyheter24 / TT","title_fi":null,"url":"https://nyheter24.se/nyheter/ekonomi/naringsliv/1517693-nyhetsbyra-i-kris-verksamhet-kan-upphora","domain":"nyheter24.se","publisher":"Nyheter24","country":"Ruotsi","country_code":"SE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"TT","type":"SYNDICATED","importance":2,"summary_fi":"TT:n uutisen jatkojulkaisu.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":6},{"id":"hist-10-6a1dc98f","cluster_id":"ntb-finsk-nyhetsbyra","title":"ABC Nyheter / NTB","title_fi":null,"url":"https://www.abcnyheter.no/nyheter/finsk-nyhetsbyra-gar-mot-avvikling/1684589","domain":"abcnyheter.no","publisher":"ABC Nyheter","country":"Norja","country_code":"NO","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"NTB","type":"SYNDICATED","importance":4,"summary_fi":"Norjan uutistoimiston uutinen STT:n mahdollisesta alasajosta.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":10},{"id":"hist-12-6612f907","cluster_id":"hist-12","title":"Tina Mari Flem / Journalisten","title_fi":null,"url":"https://www.journalisten.no/snart-kan-norden-sta-uten-et-finsk-nasjonalt-nyhetsbyra/684635","domain":"journalisten.no","publisher":"Journalisten","country":"Norja","country_code":"NO","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":"Tina Mari Flem","agency":null,"type":"COMMENT","importance":4,"summary_fi":"NTB:n toimitusjohtajan painava puheenvuoro: kansallisen uutistoimiston katoaminen heikentäisi luotettavaa tiedonvälitystä ja yhteiskunnan varautumista.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":12},{"id":"hist-13-e88bd1e8","cluster_id":"belga-stt-closure","title":"Het Nieuwsblad","title_fi":null,"url":"https://www.nieuwsblad.be/buitenland/nationale-nieuwsagentschap-van-finland-gaat-activiteiten-stopzetten/162374354.html","domain":"nieuwsblad.be","publisher":"Het Nieuwsblad","country":"Belgia","country_code":"BE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"Belga","type":"SYNDICATED","importance":3,"summary_fi":"Belgialainen uutinen STT:n uutis- ja kuvatoiminnan mahdollisesta päättymisestä maaliskuussa 2027.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"verified","source_row":13},{"id":"hist-14-4b5499fd","cluster_id":"belga-stt-closure","title":"Gazet van Antwerpen","title_fi":null,"url":null,"domain":"","publisher":"Gazet van Antwerpen","country":"Belgia","country_code":"BE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"Belga","type":"SYNDICATED","importance":2,"summary_fi":"Saman belgialaisen uutistoimistoaineiston jatkojulkaisu.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"not_verified","source_row":14},{"id":"hist-15-e04da67b","cluster_id":"belga-stt-closure","title":"Het Belang van Limburg","title_fi":null,"url":null,"domain":"","publisher":"Het Belang van Limburg","country":"Belgia","country_code":"BE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":"Belga","type":"SYNDICATED","importance":2,"summary_fi":"Saman aineiston jatkojulkaisu.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":false,"link_status":"not_verified","source_row":15},{"id":"hist-17-a9cfad16","cluster_id":"hist-17","title":"Postimees / Inbox","title_fi":null,"url":"https://news.inbox.eu/150t9k0-umberkorralduste-ootuses-soome-uudisteagentuuri-stt-ahvardab-sulgemine?language=en","domain":"news.inbox.eu","publisher":"Postimees / Inbox","country":"Viro","country_code":"EE","published_at":"2026-09-30T12:00:00+00:00","date_note":"30.9.","author":null,"agency":null,"type":"AGGREGATOR","importance":2,"summary_fi":"Virolainen uutinen STT:n uudelleenjärjestelyistä ja lakkautusuhasta.","first_seen":"2026-09-30T12:00:00+00:00","seed":true,"link_verified":true,"link_status":"mirror","source_row":17}]""")

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
  30.9.2026 alkaen. ÄLÄ palauta mitään ennen 30.9.2026 julkaistua: tämä seurattava
  tapahtuma alkoi vasta 30.9.2026. Palauta vain osumat, joita tunnetussa historiassa ei vielä ole.
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
- ÄLÄ hyväksy ennen 30.9.2026 julkaistuja osumia; ne eivät voi kuulua tähän tapahtumaseurantaan.
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

Vertaa jokaista löytöä historiaan SEMANTTISESTI. Historia sisältää auktoritatiivisen
43 havainnon lähtöaineiston 30.9.–10.10.2026. Jos FENA, Hina, Lusa/Executive Digest,
Jutarnji list, Éric Scherer tai muu historiassa jo oleva havainto löytyy uudella
otsikolla tai paremmalla URL:lla, se EI ole uusi: käytä UPDATE_EXISTING ja history_match_id.

Älä päättele uutuutta vain URL:sta. Jos sama jo tunnettu kannanotto löytyy nyt paremmalla
suoralla lähteellä, palauta se UPDATE_EXISTING-toimintona ja anna history_match_id.
Jos samalla sivulla on uusi, historiasta puuttuva merkittävän henkilön kommentti, se voi
olla oma NEW-havaintonsa.

Jos STT mainitaan aidosti vain yhtenä osiona muuten eri aihetta käsittelevässä kolumnissa
tai koosteessa, säilytä osuma (se voi olla journalistisesti kiinnostava), mutta yleensä
importance saa olla enintään 3/5. Älä tulkitse tällaista koko jutun pääaiheeksi.

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



def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def date_distance_days(a, b):
    da = _dt(a.get("published_at"))
    db = _dt(b.get("published_at"))
    if not da or not db:
        return None
    return abs((da - db).total_seconds()) / 86400.0


def seed_title_is_placeholder(item):
    title = fold_identity_text(item.get("title"))
    pub = fold_identity_text(item.get("publisher"))
    author = fold_identity_text(item.get("author"))
    agency = fold_identity_text(item.get("agency"))
    if not title:
        return True
    if pub and title == pub:
        return True
    if author and title == author:
        return True
    # Old backfill rows often used labels like "Executive Digest / Lusa".
    parts = {fold_identity_text(x) for x in re.split(r"\s*/\s*", item.get("title") or "") if x.strip()}
    known = {x for x in (pub, author, agency) if x}
    return bool(parts and parts.issubset(known))


def sanitize_existing_history(articles):
    """
    Remove prototype/search-noise rows that predate the STT event.
    The monitoring event starts on 30 Sep 2026. The authoritative 43-row
    baseline is protected separately and will be restored after cleanup.
    """
    kept = []
    removed = []
    for item in articles:
        # Protect exact baseline rows; their dates are defined by the report.
        if item.get("seed") and item.get("source_row") in BASELINE_SOURCE_ROWS:
            kept.append(item)
            continue

        d = _dt(item.get("published_at"))
        if d and d < EVENT_START:
            removed.append(item)
            continue
        kept.append(item)
    return kept, removed


def baseline_coverage(articles):
    rows = {
        int(a.get("source_row"))
        for a in articles
        if a.get("seed") and isinstance(a.get("source_row"), int)
        and a.get("source_row") in BASELINE_SOURCE_ROWS
    }
    return len(rows), sorted(BASELINE_SOURCE_ROWS - rows)


def ensure_baseline_history(articles):
    """
    Ensure the 43-row 30.9.–10.10 baseline exists before each search.
    If a baseline row is already present by id/source_row, do nothing.
    If a newer agent row clearly represents it, enrich/merge later in cleanup.
    """
    existing_ids = {a.get("id") for a in articles}
    existing_source_rows = {a.get("source_row") for a in articles if a.get("source_row")}
    added = 0
    for seed in BASELINE_HISTORY:
        if seed.get("id") in existing_ids:
            continue
        if seed.get("source_row") and seed.get("source_row") in existing_source_rows:
            continue
        articles.append(json.loads(json.dumps(seed, ensure_ascii=False)))
        existing_ids.add(seed.get("id"))
        if seed.get("source_row"):
            existing_source_rows.add(seed.get("source_row"))
        added += 1
    return articles, added


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

        days = date_distance_days(existing, item)

        # Historical seed rows often had a publisher/person label instead of the
        # real headline. Same actor + same event window + placeholder is therefore
        # the same observation, not a new one.
        if existing.get("seed") and seed_title_is_placeholder(existing):
            if days is None or days <= 3.5:
                return True

        # Wire copy found later with its real headline.
        if existing.get("seed") and existing.get("agency") and item.get("agency"):
            if fold_identity_text(existing.get("agency")) == fold_identity_text(item.get("agency")):
                if days is None or days <= 3.5:
                    return True

        # Seed backfill rows sometimes had only a person/profile and a Finnish
        # summary. A direct post by the same actor in the same time window enriches it.
        if existing.get("seed") and is_weak_or_indirect_link(existing):
            if days is None or days <= 4.5:
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
            # The report contains 43 intentional observation rows. Never collapse
            # one authoritative baseline row into another, even when several are
            # syndications of the same agency copy.
            if existing.get("seed") and item.get("seed"):
                continue

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


def actions_summary(mode, result, added, updated, rejected, cleanup_merged, baseline_restored, out_of_scope_removed, baseline_count):
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
        f"- Historical baseline rows restored: **{baseline_restored}**",
        f"- Historical baseline integrity: **{baseline_count}/43**",
        f"- Pre-30.9.2026 noise rows removed: **{out_of_scope_removed}**",
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

    # First remove old prototype/search-noise that predates the event.
    articles, removed_out_of_scope = sanitize_existing_history(articles)

    # Self-heal the authoritative 43-row baseline.
    articles, baseline_restored = ensure_baseline_history(articles)

    # Clean duplicate agent rows, but never collapse two baseline rows.
    articles, cleanup_merged = reconcile_existing_history(articles)

    # Integrity pass: even cleanup must not be able to leave the baseline incomplete.
    articles, restored_after_cleanup = ensure_baseline_history(articles)
    baseline_restored += restored_after_cleanup
    baseline_count, baseline_missing = baseline_coverage(articles)
    if baseline_missing:
        print(f"WARNING: baseline rows still missing: {baseline_missing}", file=sys.stderr)

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

        # Hard scope boundary. A story/post published before the event started
        # is not an STT closure-threat observation, no matter how similar the theme.
        raw_published = parse_date(raw.get("published_at"))
        raw_dt = _dt(raw_published) if raw_published else None
        if raw_dt and raw_dt < EVENT_START:
            rejected.append(
                f"pre-event item skipped ({raw_dt.date()}): "
                f"{raw.get('publisher')} — {raw.get('title')}"
            )
            continue

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

    actions_summary(args.mode, result, added, updated, rejected, cleanup_merged, baseline_restored, len(removed_out_of_scope), baseline_count)

    changed = bool(added or updated or cleanup_merged or baseline_restored or removed_out_of_scope)
    if not changed:
        print("No genuinely new or enrichable items. Repository data left unchanged.")
        if rejected:
            print("Skipped:")
            for x in rejected[:20]:
                print("-", x)
        return

    merged = articles + added
    merged, final_removed = sanitize_existing_history(merged)
    if final_removed:
        removed_out_of_scope.extend(final_removed)
    merged, final_restored = ensure_baseline_history(merged)
    if final_restored:
        baseline_restored += final_restored
    final_baseline_count, final_missing = baseline_coverage(merged)
    if final_baseline_count != 43:
        raise RuntimeError(f"Baseline integrity failure: {final_baseline_count}/43, missing {final_missing}")
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
        "baseline_restored": baseline_restored,
        "baseline_coverage": final_baseline_count,
        "baseline_missing_rows": final_missing,
        "out_of_scope_removed": len(removed_out_of_scope),
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
        f"baseline restored {baseline_restored}; baseline {baseline_count}/43; "
        f"removed {len(removed_out_of_scope)} pre-event rows; cleanup merged {cleanup_merged} old duplicate rows."
    )
    for a in added:
        print(f"+ {a['match_class']} {a['importance']}/5 {a['publisher']}: {a['title']}")
    for a in updated:
        print(f"~ UPDATED {a.get('publisher')}: {a.get('title')}")


if __name__ == "__main__":
    main()
