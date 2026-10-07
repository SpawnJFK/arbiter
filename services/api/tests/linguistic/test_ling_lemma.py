from __future__ import annotations

from arbiter.linguistic import has_stemmer, primary_lang, stem, to_latin, tokenize
from arbiter.linguistic.embeddings import embed


def test_tokenize_offsets_unicode():
    text = "Ugovor (član 5) — Kündigung, l'accord."
    toks = tokenize(text)
    assert [t for t, _, _ in toks] == ["Ugovor", "član", "5", "Kündigung", "l'accord"]
    for tok, a, b in toks:
        assert text[a:b] == tok


def test_serbian_inflection_and_script():
    # R-GL-03: inflected forms share a stem; Cyrillic folds to Latin for sr.
    assert stem("ugovor", "sr") == stem("ugovora", "sr") == stem("ugovorom", "sr-Latn")
    assert stem("уговором", "sr-Cyrl") == stem("ugovor", "sr")
    assert to_latin("Љубав и њива, џеп") == "Ljubav i njiva, džep"


def test_other_languages():
    assert stem("Verträge", "de") == stem("Vertrag", "de")
    assert stem("umowy", "pl") == stem("umowa", "pl")
    assert stem("Agreements", "en") == stem("agreement", "en")
    assert has_stemmer("fi") and has_stemmer("pt-BR")
    # No Snowball algorithm: lowercase identity, never an invented match.
    assert not has_stemmer("ja")
    assert stem("Tōkyō", "ja") == "tōkyō"
    assert primary_lang("sr_Latn_RS") == "sr"


def test_mock_embedding_deterministic_and_close_for_near_duplicates():
    a, b, c = embed(
        [
            "The invoice is due within thirty days.",
            "The invoice is due within 30 days.",
            "Penguins live in Antarctica.",
        ]
    )
    assert len(a) == 256
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert embed(["The invoice is due within thirty days."])[0] == a

    def cos(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert cos(a, b) > 0.7 > cos(a, c)
    assert embed([""])[0][0] == 1.0  # empty text still yields a unit vector
