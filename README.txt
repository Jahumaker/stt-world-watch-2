STT WORLD WATCH – AI-AGENTTIPÄIVITYS

Tämä paketti ei sisällä articles.json- tai status.json-tiedostoja, jotta nykyinen 43 osuman historia ei vahingossa ylikirjoitu.

Vaihda repossa:
1) update_news.py -> tämän paketin update_news.py
2) requirements.txt -> tämän paketin requirements.txt
3) index.html -> tämän paketin index.html
4) .github/workflows/update-news.yml -> kopioi WORKFLOW-COPY-PASTE.txt:n sisältö tähän tiedostoon

GitHub Secretin OPENAI_API_KEY pitää olla olemassa.

Testi:
Actions -> Update STT World Watch -> Run workflow -> mode: deep.

Onnistuneessa ajossa Actions Summary näyttää:
- Agent candidates
- New accepted items
- Rejected/unverifiable candidates
- Agent summary

Jos uusia osumia löytyy, ne lisätään nykyiseen articles.json-historiaan. Jos ei löydy, articles.json ja status.json jätetään koskematta.
