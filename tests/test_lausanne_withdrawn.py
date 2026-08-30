"""Offline tests for Lausanne 2026 Olympic withdrawal shapes.

Fixtures were sliced from the live capture at the tail end of the men's and women's Olympic
races (2026-08-30 ~09:44 UTC). They document how Datasport surfaces DNFs on gender versus
age-group lists -- behaviour the poller must account for when classifying withdrawals.
"""

from __future__ import annotations

import json
from pathlib import Path

from racedata.providers.datasport.parse import (
    cell_text,
    split_ranked_and_withdrawn,
    target_slug,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lausanne-2026-withdrawn"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _rows(payload: dict) -> list:
    table = payload.get("table") or {}
    return list(table.get("rows") or [])


# -- Fixture corpus ---------------------------------------------------------------------
def test_fixture_manifest_matches_expectations():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())

    assert manifest["femmes-cla-overall.json"]["withdrawn_rows"] == 3
    assert manifest["hommes-cla-overall.json"]["withdrawn_rows"] == 0
    assert manifest["hommes-cla-35-44-overall.json"]["withdrawn_rows"] == 3
    assert manifest["hommes-cla-35-44-split-281.json"]["withdrawn_rows"] == 1


def test_withdrawn_rows_carry_name_but_not_rank_or_time():
    """Guarding on ``name`` alone would treat every DNF as ranked."""
    for fixture in (
        "femmes-cla-overall.json",
        "hommes-cla-35-44-overall.json",
        "hommes-cla-35-44-split-281.json",
    ):
        _, withdrawn = split_ranked_and_withdrawn(_rows(_load(fixture)))
        assert withdrawn, f"expected a DNF block in {fixture}"
        for row in withdrawn:
            assert cell_text(row, "name")
            assert row.get("rank.main") is None
            assert not cell_text(row, "time.main")
            assert target_slug(row)


def test_femmes_gender_list_carries_the_dnf_block():
    ranked, withdrawn = split_ranked_and_withdrawn(_rows(_load("femmes-cla-overall.json")))

    assert len(ranked) == 151
    assert {target_slug(row) for row in withdrawn} == {
        "mussin-eliana",
        "gondre-maude",
        "bertschy-elodie",
    }


def test_hommes_gender_list_page_has_finishers_but_no_dnf_block():
    """Men's DNFs did not appear on the gender list in our capture, even with 472 starters."""
    ranked, withdrawn = split_ranked_and_withdrawn(_rows(_load("hommes-cla-overall.json")))

    assert len(ranked) == 200
    assert withdrawn == []
    assert _load("hommes-cla-overall.json")["table"]["totalrowcount"] == 472


def test_hommes_agegroup_list_carries_the_dnf_block():
    ranked, withdrawn = split_ranked_and_withdrawn(_rows(_load("hommes-cla-35-44-overall.json")))

    assert ranked
    assert {target_slug(row) for row in withdrawn} == {
        "casado-pepe",
        "thomas-cyrille",
        "haessig-reto",
    }


def test_mens_gender_and_agegroup_lists_disagree_on_dnf_visibility():
    """The poller's ``fetch_standings_bundle`` only reads the gender list.

    When the gender list omits the DNF block -- as ``hommes-cla`` did in the 2026 capture --
    every age-group ladder derived from that bundle inherits an empty ``withdrawn`` tuple.
    Age-group list queries are required to detect men's retirements.
    """
    _, gender_withdrawn = split_ranked_and_withdrawn(_rows(_load("hommes-cla-overall.json")))
    _, age_withdrawn = split_ranked_and_withdrawn(_rows(_load("hommes-cla-35-44-overall.json")))

    assert gender_withdrawn == []
    assert len(age_withdrawn) == 3


def test_checkpoint_query_can_still_surface_a_dnf():
    """Withdrawn athletes are not guaranteed on every checkpoint query."""
    _, withdrawn = split_ranked_and_withdrawn(_rows(_load("hommes-cla-35-44-split-281.json")))

    assert {target_slug(row) for row in withdrawn} == {"casado-pepe"}
