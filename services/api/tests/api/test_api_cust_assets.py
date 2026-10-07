"""Glossaries, TM and term questions over HTTP (R-GL-11, R-TM-01, R-TM-06)."""

from __future__ import annotations

from api_helpers import client, register
from sqlalchemy import select

from arbiter.models import Organization, Term, TermQuestion

TMX = b"""<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4"><header srclang="en" datatype="plaintext" segtype="sentence" adminlang="en"
 creationtool="test" creationtoolversion="1" o-tmf="none"/>
<body>
<tu><tuv xml:lang="en"><seg>Open the settings page.</seg></tuv>
<tuv xml:lang="sr"><seg>Otvorite stranicu podesavanja.</seg></tuv></tu>
</body></tmx>"""


def test_r_gl_11_glossary_crud_and_csv_round_trip(db):
    c = client()
    h = register(c)
    g = c.post("/v1/glossaries", headers=h, json={"name": "Main"}).json()
    assert g["term_count"] == 0
    t = c.post(
        f"/v1/glossaries/{g['id']}/terms",
        headers=h,
        json={"source_lang": "en", "target_lang": "sr", "source_term": "contract", "target_term": "ugovor"},
    )
    assert t.status_code == 201, t.text
    term = t.json()
    assert term["kind"] == "mandatory" and term["valid_to"] is None
    bad = c.post(
        f"/v1/glossaries/{g['id']}/terms",
        headers=h,
        json={"source_lang": "en", "target_lang": "sr", "source_term": "invoice", "kind": "mandatory"},
    )
    assert bad.status_code == 422  # a mandatory term needs a target

    upd = c.patch(f"/v1/terms/{term['id']}", headers=h, json={"target_term": "ugovora"})
    assert upd.status_code == 200
    new = upd.json()
    assert new["id"] != term["id"] and new["target_term"] == "ugovora"
    assert c.patch(f"/v1/terms/{term['id']}", headers=h, json={"note": "x"}).status_code == 409

    found = c.get(f"/v1/glossaries/{g['id']}/terms?q=contr", headers=h).json()["items"]
    assert [x["id"] for x in found] == [new["id"]]
    assert c.get(f"/v1/glossaries/{g['id']}/terms?q=zzz", headers=h).json()["items"] == []

    csv = "source_term,target_term,kind\ninvoice,faktura,mandatory\nAPI,,do_not_translate\n"
    r = c.post(
        f"/v1/glossaries/{g['id']}/import",
        headers=h,
        files={"file": ("terms.csv", csv.encode())},
        data={"source_lang": "en", "target_lang": "sr"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2 and r.json()["errors"] == []
    lst = c.get("/v1/glossaries", headers=h).json()["items"]
    assert lst[0]["term_count"] == 3 and lst[0]["version"] > g["version"]

    exp = c.get(f"/v1/glossaries/{g['id']}/export?format=csv", headers=h)
    assert exp.status_code == 200 and "faktura" in exp.text and "ugovora" in exp.text
    tbx = c.get(f"/v1/glossaries/{g['id']}/export?format=tbx", headers=h)
    assert tbx.status_code == 200 and b"faktura" in tbx.content

    # TBX re-import into a second glossary: the language comes from the file's root xml:lang
    g2 = c.post("/v1/glossaries", headers=h, json={"name": "Copy"}).json()
    r = c.post(f"/v1/glossaries/{g2['id']}/import", headers=h, files={"file": ("g.tbx", tbx.content)})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] >= 2

    assert c.delete(f"/v1/terms/{new['id']}", headers=h).status_code == 204
    counts = {x["id"]: x["term_count"] for x in c.get("/v1/glossaries", headers=h).json()["items"]}
    assert counts[g["id"]] == 2
    db.expire_all()
    assert db.get(Term, new["id"]).valid_to is not None  # retired, history kept


def test_r_tm_01_tmx_import_requires_rights(db):
    c = client()
    h = register(c)
    r = c.post("/v1/tm/import", headers=h, files={"file": ("mem.tmx", TMX)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "rights_not_confirmed"
    r = c.post(
        "/v1/tm/import", headers=h, files={"file": ("mem.tmx", TMX)}, data={"rights_confirmed": "true"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1
    hits = c.get(
        "/v1/tm/search",
        headers=h,
        params={"q": "Open the settings page.", "source_lang": "en", "target_lang": "sr"},
    ).json()["items"]
    assert hits and hits[0]["kind"] == "exact" and hits[0]["score"] == 100.0
    exp = c.get("/v1/tm/export?source_lang=en&target_lang=sr", headers=h)
    assert exp.status_code == 200 and b"podesavanja" in exp.content

    from arbiter.models import TmEntry, User

    db.expire_all()
    user = db.execute(select(User)).scalar_one()
    assert db.execute(select(TmEntry)).scalar_one().rights_confirmed_by == user.id

    other = register(c, email="o@example.com", org="Other")
    none = c.get(
        "/v1/tm/search",
        headers=other,
        params={"q": "Open the settings page.", "source_lang": "en", "target_lang": "sr"},
    ).json()["items"]
    assert none == []


def test_r_tm_06_term_question_answer_adds_mandatory_term(db):
    c = client()
    h = register(c)
    g = c.post("/v1/glossaries", headers=h, json={"name": "Main"}).json()
    org = db.execute(select(Organization)).scalar_one()
    tq = TermQuestion(
        org_id=org.id,
        source_lang="en",
        target_lang="sr",
        source_term="dashboard",
        options=["kontrolna tabla"],
    )
    db.add(tq)
    db.commit()
    lst = c.get("/v1/term-questions?status=open", headers=h).json()["items"]
    assert [x["id"] for x in lst] == [tq.id]
    r = c.post(
        f"/v1/term-questions/{tq.id}/answer",
        headers=h,
        json={"answer": "kontrolna tabla", "add_to_glossary_id": g["id"]},
    )
    assert r.status_code == 200 and r.json()["status"] == "answered"
    terms = c.get(f"/v1/glossaries/{g['id']}/terms", headers=h).json()["items"]
    assert terms[0]["source_term"] == "dashboard" and terms[0]["kind"] == "mandatory"
    again = c.post(f"/v1/term-questions/{tq.id}/answer", headers=h, json={"answer": "x"})
    assert again.status_code == 409
