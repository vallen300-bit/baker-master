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


# --- AC1 round-2 — real AO_MASTER prod paths (no literal 'Oskolkov' in path) hint to AO ---
# Round-1 only tested a path literally containing 'Oskolkov'. The real corpus lives under
# /Baker-Feed/AO_MASTER/... with NO 'Oskolkov' substring — the gap codex #6935 caught: the
# generic 'RG7' -> 'Riemergasse 7' hint won first-match for these. Each path below is a real
# prod source_path (verified live) from a distinct AO_MASTER subtree family.

@pytest.mark.parametrize("src", [
    # AO_in_RG7 financial subtree (was mislabeled 'Baker'); contains 'RG7' -> must NOT go to Riemergasse
    "/Baker-Feed/AO_MASTER/10_AO_RG7_2025/AO_in_RG7/Financial/General 2014-2025/TRANSACTIONS/1.45 MLN Private A:C AO CBH/22497 2.pdf",
    # AO GF / mezz subtree (was mislabeled 'Cap Ferrat Villa')
    "/Baker-Feed/AO_MASTER/AO GF/AO Mezz 6 mln 2023/15_07_23 Payments Schedule 2023-2024.xlsx",
    # AO GF / project-list subtree (was mislabeled 'Cupial')
    "/Baker-Feed/AO_MASTER/AO GF/Boxing/AO Project List/AO CYPRUS/AO PASSPORT CUPRUS.pdf",
    # AO_RG7 reconciliation doc that lives OUTSIDE AO_MASTER (email source)
    "email:19d4e5be10c4049c/50448752_AO_RG7_Reconciliation_For_Confirmation.docx",
])
def test_ac1_round2_ao_master_paths_hint_oskolkov_not_riemergasse(src):
    """Every AO_MASTER / AO_RG7 prod path hints the AO matter ('Oskolkov'), never the
    generic 'Riemergasse 7' (the first-match collision codex #6935 flagged)."""
    hint = get_path_matter_hint(src)
    assert "Oskolkov" in hint, f"AO path did not hint Oskolkov: {src!r} -> {hint!r}"
    assert "Riemergasse" not in hint, f"AO path wrongly hinted Riemergasse: {src!r}"
    assert "Oskolkov-RG7" not in hint


def test_regression_generic_rg7_still_hints_riemergasse():
    """A non-AO path containing only the generic 'RG7' token still resolves to
    'Riemergasse 7' — the AO_* keys must not steal genuine Riemergasse docs."""
    src = "/Baker-Feed/Riemergasse 7 Sanierung/RG7 Bauakt/Nachtrag_03.pdf"
    hint = get_path_matter_hint(src)
    assert "Riemergasse 7" in hint
    assert "Oskolkov" not in hint


def test_ordering_ao_keys_precede_generic_rg7():
    """Foot-gun guard: AO root-scope keys MUST iterate before the generic 'RG7' key,
    because get_path_matter_hint returns first-match. A future edit that reorders the
    dict and puts an AO key after 'RG7' would silently reintroduce the mislabel."""
    keys = list(PATH_MATTER_HINTS.keys())
    assert "RG7" in keys and "AO_MASTER" in keys and "AO_RG7" in keys
    assert keys.index("AO_MASTER") < keys.index("RG7")
    assert keys.index("AO_RG7") < keys.index("RG7")


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
