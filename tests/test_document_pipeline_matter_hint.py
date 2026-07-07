"""AO_LABEL_MAP_CANONICAL_FIX_1 — the Oskolkov classification hint must steer new
docs to the canonical `ao` matter, and the retired combined label `Oskolkov-RG7`
must no longer be mintable by the document-pipeline hint map.

Context: `Oskolkov-RG7` was a COMBINED label b1 split (511 docs → ao=301 dominant,
hagenauer-rg7=71, mo-vie-am=46, mrci=22, steininger=10, lilienmatt=4). It is retired.
Landmine (verified): in slugs.yml `Oskolkov-RG7` is an ALIAS of `hagenauer-rg7`, NOT
`ao` — so any re-minted `Oskolkov-RG7` label mis-normalizes to the wrong matter. The
canonical hint for the AO folder is `Oskolkov`, which normalizes to slug `ao`.
"""

import pytest

from tools.document_pipeline import PATH_MATTER_HINTS, get_path_matter_hint


# --- AC2 — Oskolkov-RG7 is not mintable via the document-pipeline hint map ---

def test_ac2_oskolkov_rg7_not_a_mintable_hint_value():
    """No PATH_MATTER_HINTS entry may emit the retired combined label."""
    assert "Oskolkov-RG7" not in PATH_MATTER_HINTS.values()


def test_ac2_oskolkov_folder_hint_is_canonical_oskolkov():
    """The 'Oskolkov' folder pattern maps to the canonical 'Oskolkov' hint."""
    assert PATH_MATTER_HINTS.get("Oskolkov") == "Oskolkov"


# --- AC1 — a new doc from an Oskolkov folder is hinted to the AO matter ---

def test_ac1_oskolkov_path_hint_names_oskolkov_not_rg7():
    """A real Oskolkov source path produces a hint naming 'Oskolkov' (the AO matter),
    never the retired 'Oskolkov-RG7'."""
    src = "/Baker-Project/01_Projects/Active_Projects/Oskolkov/Media and Files/deal.pdf"
    hint = get_path_matter_hint(src)
    assert "Oskolkov" in hint
    assert "Oskolkov-RG7" not in hint


def test_ac1_oskolkov_hint_normalizes_to_ao():
    """The 'Oskolkov' hint value canonicalizes to slug 'ao' (the real classifier
    downstream path). Skips only if the slug registry (slugs.yml) is unavailable."""
    try:
        from kbl import slug_registry
        canonical = slug_registry.normalize("Oskolkov")
    except Exception as exc:  # registry/vault not loadable in this env
        pytest.skip(f"slug_registry unavailable: {exc}")
    assert canonical == "ao"


# --- Regression — the legacy fold is deliberately UNTOUCHED (landmine = separate PR) ---

def test_regression_legacy_rg7_fold_unchanged():
    """`Oskolkov-RG7` still normalizes to hagenauer-rg7 (legacy read-side fold). This
    fix does NOT touch that fold; the slugs.yml oskolkov-rg7→hagenauer-rg7 mis-alias is
    handled by a separate baker-vault-slugs PR. Confirms the diff stayed surgical."""
    try:
        from kbl import slug_registry
        legacy = slug_registry.normalize("Oskolkov-RG7")
    except Exception as exc:
        pytest.skip(f"slug_registry unavailable: {exc}")
    assert legacy == "hagenauer-rg7"
