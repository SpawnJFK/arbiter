"""TM tools API: TM editor, alignment (R-TM-01 on commit), term extraction, TM QA."""

from __future__ import annotations

from sqlalchemy import select
from tms_helpers import client, client_user, order, register

from arbiter.linguistic import tm
from arbiter.models import Term, TmEntry, User

SRC_DOC = (
    b"# Contract terms\n\n"
    b"The service contract starts on 1 March. The service contract ends after 12 months.\n\n"
    b"Payment terms are 30 days. Late payment terms apply after that.\n"
)
TGT_DOC = (
    b"# Uslovi ugovora\n\n"
    b"Ugovor o usluzi pocinje 1. marta. Ugovor o usluzi istice posle 12 meseci.\n\n"
    b"Rok placanja je 30 dana. Nakon toga vaze uslovi za kasno placanje.\n"
)


def _org(db) -> str:
    return db.execute(select(User.org_id)).scalars().first()


def test_tm_editor_search_patch_delete_bulk(db):
    c = client()
    h = register(c)
    ch = client_user(db, c, h)
    org = _org(db)
    a = tm.store(db, org, "en", "de", "Open the file.", "Offnen Sie die Datei.")
    b = tm.store(db, org, "en", "de", "Close the file.", "Schliessen Sie die Datei.")
    tm.store(db, org, "en", "fr", "Open the file.", "Ouvrez le fichier.")
    db.commit()
    r = c.get("/v1/tm/entries", headers=h, params={"q": "datei", "source_lang": "en", "target_lang": "de"})
    assert r.status_code == 200 and {e["id"] for e in r.json()["items"]} == {a.id, b.id}
    assert len(c.get("/v1/tm/entries", headers=h, params={"target_lang": "fr"}).json()["items"]) == 1
    assert len(c.get("/v1/tm/entries", headers=h, params={"origin": "import"}).json()["items"]) == 0
    assert len(c.get("/v1/tm/entries", headers=h, params={"created_from": "2020-01-01"}).json()["items"]) == 3
    assert c.get("/v1/tm/entries", headers=h, params={"created_to": "2020-01-01"}).json()["items"] == []

    r = c.patch(
        f"/v1/tm/entries/{a.id}", headers=h, json={"target_tagged": "Offne die Datei.", "status": "stale"}
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "stale"
        and r.json()["target_tagged"] == "Offne die Datei."
    )
    # a stale entry is never served (R-TM-02)
    assert tm.lookup(db, org, "en", "de", "Open the file.") == [] or all(
        m.entry_id != a.id for m in tm.lookup(db, org, "en", "de", "Open the file.")
    )
    r = c.patch(f"/v1/tm/entries/{a.id}", headers=h, json={"source_tagged": "Open this file."})
    db.expire_all()
    assert db.get(TmEntry, a.id).source_hash == tm.source_hash("Open this file.", "en")
    assert c.patch(f"/v1/tm/entries/{a.id}", headers=ch, json={"status": "approved"}).status_code == 403
    r = c.post("/v1/tm/entries/bulk", headers=h, json={"ids": [a.id, b.id], "action": "mark_approved"})
    assert r.json()["changed"] == 2
    assert c.delete(f"/v1/tm/entries/{b.id}", headers=h).status_code == 204
    assert c.delete(f"/v1/tm/entries/{b.id}", headers=h).status_code == 404
    r = c.post("/v1/tm/entries/bulk", headers=h, json={"ids": [a.id], "action": "delete"})
    assert r.json()["changed"] == 1
    h2 = register(c, "o@example.com", "Other")
    remaining = c.get("/v1/tm/entries", headers=h).json()["items"][0]["id"]
    assert c.delete(f"/v1/tm/entries/{remaining}", headers=h2).status_code == 404


def test_alignment_review_grid_and_commit_with_rights(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/tm/align",
        headers=h,
        files={"source_file": ("en.md", SRC_DOC), "target_file": ("sr.md", TGT_DOC)},
        data={"source_lang": "en", "target_lang": "sr"},
    )
    assert r.status_code == 201, r.text
    al = r.json()
    pairs = al["pairs"]
    assert al["status"] == "review" and len(pairs) == 5
    assert all(len(p["src"]) == 1 and len(p["tgt"]) == 1 for p in pairs)
    assert pairs[1]["source"].startswith("The service contract starts") and "1. marta" in pairs[1]["target"]
    assert all(0 <= p["confidence"] <= 1 for p in pairs)
    assert c.get(f"/v1/tm/align/{al['id']}", headers=h).json()["id"] == al["id"]

    r = c.post(f"/v1/tm/align/{al['id']}/commit", headers=h, json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "rights_not_confirmed"
    edits = [
        {"index": 0, "accepted": False},
        {"index": 4, "accepted": True, "target": "Posle toga vaze uslovi."},
    ]
    edits += [{"index": i, "accepted": True} for i in (1, 2, 3)]
    r = c.post(f"/v1/tm/align/{al['id']}/commit", headers=h, json={"rights_confirmed": True, "pairs": edits})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 4
    entries = db.execute(select(TmEntry)).scalars().all()
    assert len(entries) == 4 and all(e.origin == "import" and e.rights_confirmed_by for e in entries)
    assert any(e.target_plain == "Posle toga vaze uslovi." for e in entries)
    assert (
        c.post(f"/v1/tm/align/{al['id']}/commit", headers=h, json={"rights_confirmed": True}).status_code
        == 409
    )
    bad = c.post(
        "/v1/tm/align",
        headers=h,
        files={"source_file": ("en.pdf", b"%PDF"), "target_file": ("sr.md", TGT_DOC)},
        data={"source_lang": "en", "target_lang": "sr"},
    )
    assert bad.status_code == 422


def test_term_extraction_from_job_and_file_then_accept(db):
    c = client()
    h = register(c)
    g = c.post("/v1/glossaries", headers=h, json={"name": "Legal"}).json()
    org = _org(db)
    tm.store(db, org, "en", "sr", "The service contract is valid.", "Ugovor o usluzi je vazeci.")
    tm.store(db, org, "en", "sr", "Sign the service contract.", "Potpisite ugovor o usluzi.")
    tm.store(db, org, "en", "sr", "Read the payment terms.", "Procitajte uslove placanja.")
    db.commit()
    r = c.post(
        f"/v1/glossaries/{g['id']}/extract",
        headers=h,
        files={"file": ("en.md", SRC_DOC)},
        data={"source_lang": "en", "target_lang": "sr"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    terms = {i["source_term"].lower(): i for i in items}
    assert "service contract" in terms and "payment terms" in terms
    # nested "service" never occurs outside "service contract": dropped
    assert "service" not in terms
    # stopwords never start or end a candidate
    assert not any(t.split()[0] in ("the", "after") for t in terms)
    sc = terms["service contract"]
    assert sc["frequency"] == 2 and sc["target_candidates"]
    assert any("ugovor" in t["term"].lower() for t in sc["target_candidates"])

    job = order(c, h)
    r = c.post(f"/v1/glossaries/{g['id']}/extract", headers=h, data={"job_id": job["id"], "min_freq": 1})
    assert r.status_code == 200 and r.json()["job_id"] == job["id"] and r.json()["items"]
    assert c.post(f"/v1/glossaries/{g['id']}/extract", headers=h, data={}).status_code == 422

    acc = {
        "terms": [
            {"source_term": "service contract", "target_term": "ugovor o usluzi", "kind": "mandatory",
             "source_lang": "en", "target_lang": "sr"},
        ]
    }  # fmt: skip
    r = c.post(f"/v1/glossaries/{g['id']}/extract/accept", headers=h, json=acc)
    assert r.status_code == 201 and r.json()["items"][0]["kind"] == "mandatory"
    assert db.execute(select(Term)).scalar_one().source_term == "service contract"
    # accepted terms are skipped on the next run
    again = c.post(
        f"/v1/glossaries/{g['id']}/extract",
        headers=h,
        files={"file": ("en.md", SRC_DOC)},
        data={"source_lang": "en", "target_lang": "sr"},
    ).json()["items"]
    assert "service contract" not in {i["source_term"].lower() for i in again}
    bad = {"terms": [{"source_term": "x", "kind": "mandatory", "source_lang": "en", "target_lang": "sr"}]}
    assert c.post(f"/v1/glossaries/{g['id']}/extract/accept", headers=h, json=bad).status_code == 422


def test_tm_qa_inconsistencies_and_glossary(db):
    c = client()
    h = register(c)
    org = _org(db)
    tm.store(db, org, "en", "sr", "Save the file.", "Sacuvajte datoteku.", context_hash="a")
    tm.store(db, org, "en", "sr", "Save the file.", "Snimite fajl.", context_hash="b")
    tm.store(db, org, "en", "sr", "Save the file.", "sacuvajte  datoteku.", context_hash="c")
    tm.store(db, org, "en", "sr", "Open the file.", "Otvorite datoteku.")
    db.commit()
    g = c.post("/v1/glossaries", headers=h, json={"name": "UI"}).json()
    c.post(
        f"/v1/glossaries/{g['id']}/terms",
        headers=h,
        json={"source_lang": "en", "target_lang": "sr", "source_term": "file", "target_term": "datoteka"},
    )
    r = c.get(
        "/v1/tm/qa", headers=h, params={"source_lang": "en", "target_lang": "sr", "glossary_id": g["id"]}
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["inconsistent"]) == 1
    group = body["inconsistent"][0]
    assert group["source_tagged"] == "Save the file." and len(group["variants"]) == 2
    assert sorted(len(v["entry_ids"]) for v in group["variants"]) == [1, 2]
    viol = body["glossary_violations"]
    assert [v["target_tagged"] for v in viol] == ["Snimite fajl."]
    assert viol[0]["violations"][0]["code"] == "term_missing"
