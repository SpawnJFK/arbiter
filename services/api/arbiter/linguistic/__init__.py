"""Linguistic assets: lemmatized glossary matching, versioned glossaries, TM, embeddings.

Other modules talk to this package through contracts.py types (TermHit,
TermViolation, TmMatch) and the functions exported here.
"""

from __future__ import annotations

from arbiter.linguistic.embeddings import embed
from arbiter.linguistic.glossary import (
    TERM_KINDS,
    active_terms,
    add_term,
    check_target,
    count_occurrences,
    create_glossary,
    current_version,
    export_csv,
    export_tbx,
    find_source_terms,
    import_csv,
    import_tbx,
    retire_term,
    update_term,
)
from arbiter.linguistic.lemma import has_stemmer, norm_lang, primary_lang, stem, to_latin, tokenize
from arbiter.linguistic.tm import (
    context_hash,
    export_tmx,
    import_tmx,
    lookup,
    source_hash,
    store,
    tagged_plain,
)

__all__ = [
    "TERM_KINDS",
    "active_terms",
    "add_term",
    "check_target",
    "context_hash",
    "count_occurrences",
    "create_glossary",
    "current_version",
    "embed",
    "export_csv",
    "export_tbx",
    "export_tmx",
    "find_source_terms",
    "has_stemmer",
    "import_csv",
    "import_tbx",
    "import_tmx",
    "lookup",
    "norm_lang",
    "primary_lang",
    "retire_term",
    "source_hash",
    "stem",
    "store",
    "tagged_plain",
    "to_latin",
    "tokenize",
    "update_term",
]
