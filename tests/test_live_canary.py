"""Live schema canary.

    pytest -m live

These tests hit the real timing API. They are excluded from the default run and exist to
answer one question in the run-up to a race: **has the upstream contract drifted?**

That matters here more than usual. List slugs demonstrably rotate between editions, split
ids can be reassigned, and several failures come back as HTTP 200 with a plausible body. A
scheduled run of this file turns "the app broke on race morning" into "a test went red a
week earlier".
"""

from __future__ import annotations

import pytest

from racedata.core.models import Race
from racedata.core.standings import Division
from racedata.providers.datasport.client import DatasportClient
from racedata.providers.datasport.parse import (
    OrderNotAppliedError,
    applied_checkpoint_label,
    assert_order_applied,
    checkpoint_catalog,
    contest_lists,
    country_alpha3,
    parse_time_tenths,
    split_ranked_and_withdrawn,
)
from racedata.providers.datasport.service import DatasportProvider

pytestmark = pytest.mark.live

TARGET = "powerman-world-championships-zofingen-2026"
REFERENCE = "powerman-world-championships-zofingen-2025"
GENDER_LIST = "world-triathlon-men-age-group"
LAUSANNE = "triathlon-lausanne-2026"
LAUSANNE_MEN = "hommes-cla"
LAUSANNE_MEN_35_44 = "hommes-cla-35-44"


@pytest.fixture(scope="module")
def client() -> DatasportClient:
    return DatasportClient()


@pytest.fixture(scope="module")
def provider(client: DatasportClient) -> DatasportProvider:
    return DatasportProvider(client)


# -- The target event still exists in the shape we expect -------------------------------
def test_target_edition_still_resolves(provider: DatasportProvider):
    race = Race(event_key=TARGET, display_name="Zofingen 2026", provider="datasport")

    divisions = provider.list_divisions(race)

    assert divisions, "no divisions for the target edition -- has the slug changed?"
    assert any(d.scope == "agegroup" for d in divisions)


def test_divisions_come_from_the_start_list_before_results_exist(client: DatasportClient):
    """The pre-race asymmetry the app depends on. If ranking starts returning a tree, that is
    a behaviour change worth knowing about, not a failure."""
    ranking = contest_lists(client.call("ranking", edition=TARGET).payload)
    startlist = contest_lists(client.call("startlist", edition=TARGET).payload)

    assert startlist, "the start list must expose the contest tree before the race"
    if ranking:
        pytest.skip("ranking now returns a tree too; the race may have started")


def test_roster_list_slugs_still_exist(provider: DatasportProvider):
    """Slugs rotate between editions; this is the check most likely to save race day."""
    import json
    from pathlib import Path

    config = Path(__file__).resolve().parent.parent / "config" / "roster.zofingen-2026.json"
    document = json.loads(config.read_text())
    race = Race(event_key=TARGET, display_name="x", provider="datasport")
    available = {d.id for d in provider.list_divisions(race)}

    referenced = {
        slug
        for athlete in document["athletes"]
        for slug in (athlete.get("gender_list_slug"), athlete.get("agegroup_list_slug"))
        if slug
    }

    assert referenced <= available, f"slugs no longer exist: {sorted(referenced - available)}"


def test_every_tracked_favorite_id_still_resolves(provider: DatasportProvider):
    """Unknown ids are dropped silently with a 200, so 23 requested can render as 22."""
    import json
    from pathlib import Path

    config = Path(__file__).resolve().parent.parent / "config" / "roster.zofingen-2026.json"
    document = json.loads(config.read_text())
    ids = [a["favorite_id"] for a in document["athletes"] if a.get("favorite_id")]
    race = Race(event_key=TARGET, display_name="x", provider="datasport")

    _, missing = provider.fetch_favorites(race, ids)

    assert missing == [], f"favorite ids no longer resolve: {missing}"


def test_checkpoint_ids_and_labels_are_unchanged(provider: DatasportProvider):
    race = Race(event_key=TARGET, display_name="x", provider="datasport")
    division = Division(id=GENDER_LIST, label="men")

    catalog = provider.checkpoint_catalog_for(race, division)

    assert len(catalog) >= 25, f"expected the full Zofingen ladder, got {len(catalog)}"
    labels = {label for _, label in catalog}
    for expected in ("Run1 - Heitere 1", "Bike - WZ IN", "Run2 - Heitere 1", "Finish"):
        assert expected in labels, f"checkpoint {expected!r} has disappeared"


def test_the_two_multi_crossing_mats_are_still_the_expected_ones(provider: DatasportProvider):
    """Configured explicitly, so a change in the course would otherwise go unnoticed."""
    race = Race(event_key=TARGET, display_name="x", provider="datasport")
    division = Division(id=GENDER_LIST, label="men")

    labels = {label for _, label in provider.checkpoint_catalog_for(race, division)}

    assert {"Run2 - WZ OUT", "Run2 - WZ IN"} <= labels


# -- Guard behaviours, checked against the live service ---------------------------------
def test_order_guard_accepts_a_valid_ordering(client: DatasportClient):
    catalog = checkpoint_catalog(
        client.call("ranking", edition=REFERENCE, slug=GENDER_LIST, count=1).payload
    )
    order, label = catalog[len(catalog) // 2]

    payload = client.call(
        "ranking", edition=REFERENCE, slug=GENDER_LIST, order=order, count=5
    ).payload

    assert_order_applied(payload, order, expected_label=label)
    assert applied_checkpoint_label(payload) == label


def test_order_guard_still_catches_a_rejected_ordering(client: DatasportClient):
    """The core silent failure: an unknown order is ignored and 200 comes back in default
    order. If this ever stops raising, the guard has stopped working."""
    payload = client.call(
        "ranking", edition=REFERENCE, slug=GENDER_LIST, order="split-99999", count=5
    ).payload

    with pytest.raises(OrderNotAppliedError):
        assert_order_applied(payload, "split-99999")


def test_a_rotated_slug_returns_200_with_no_table(client: DatasportClient):
    """Documents the behaviour the ListNotFoundError guard exists for.

    Uses a real historical rotation: the long-distance open men's list was
    ``ld-open-men-age-group`` in 2025 and ``open-men-age-group`` in 2026. Asking the 2026
    edition for the 2025 slug is exactly the mistake a hardcoded slug would make -- and the
    answer is a cheerful 200 with no table, not a 404.
    """
    stale = client.call("ranking", edition=TARGET, slug="ld-open-men-age-group", count=5)
    assert stale.table is None, "a rotated slug should yield no table"

    # Sanity check that the slug is genuinely a 2025-only name, so this test is not
    # passing merely because the list never existed.
    original = client.call("ranking", edition=REFERENCE, slug="ld-open-men-age-group", count=5)
    assert original.table is not None


def test_times_are_still_comma_decimal_and_parseable(client: DatasportClient):
    response = client.call_all_pages("ranking", edition=REFERENCE, slug=GENDER_LIST)
    ranked, _ = split_ranked_and_withdrawn(response.rows)

    assert ranked
    sample = ranked[0]
    text = sample["time.main"]["text"]
    assert "," in text, f"time format changed: {text!r}"
    assert parse_time_tenths(text) is not None


def test_withdrawn_rows_still_carry_a_name_but_no_rank(client: DatasportClient):
    """Guarding on `name` would classify every withdrawal as a ranked competitor."""
    catalog = checkpoint_catalog(
        client.call("ranking", edition=REFERENCE, slug=GENDER_LIST, count=1).payload
    )
    order, _ = catalog[0]
    response = client.call_all_pages(
        "ranking", edition=REFERENCE, slug=GENDER_LIST, order=order
    )

    _, withdrawn = split_ranked_and_withdrawn(response.rows)

    assert withdrawn, "expected a DNF block at an early checkpoint"
    for row in withdrawn:
        assert row.get("name")
        assert row.get("rank.main") is None


def test_country_is_still_only_available_from_the_flag_filename(client: DatasportClient):
    response = client.call_all_pages("startlist", edition=TARGET, slug=GENDER_LIST)

    assert response.rows
    assert any(country_alpha3(row) for row in response.rows)
    # If a real country field ever appears, simplify the provider.
    assert not any("country" in row for row in response.rows[:20])


def test_conditional_refresh_still_short_circuits(client: DatasportClient):
    first = client.call("ranking", edition=REFERENCE, slug=GENDER_LIST, count=5)
    assert first.refresh_token

    again = client.call(
        "ranking", edition=REFERENCE, slug=GENDER_LIST, count=5, refresh=first.refresh_token
    )

    assert again.unchanged is True


def test_paging_cap_is_still_two_hundred(client: DatasportClient):
    response = client.call(
        "ranking", edition=REFERENCE, slug=GENDER_LIST, count=3000, page=1
    )

    assert response.table is not None
    assert len(response.rows) <= 200


def test_lausanne_mens_dnfs_are_not_on_the_gender_list(client: DatasportClient):
    """Captured 2026-08-30: ``hommes-cla`` had finishers but no DNF block, while
    ``hommes-cla-35-44`` carried withdrawn athletes on the same day.

    The poller must not assume the gender list's withdrawn tuple is complete for men.
    """
    agegroup = client.call(
        "ranking", edition=LAUSANNE, slug=LAUSANNE_MEN_35_44, count=200, page=1
    )
    if agegroup.stage not in {"live", "done"} or agegroup.table is None:
        pytest.skip("Lausanne Olympic results are not published yet")

    _, withdrawn_agegroup = split_ranked_and_withdrawn(agegroup.rows)
    if not withdrawn_agegroup:
        pytest.skip("no DNFs on the men's 35-44 list yet")

    gender = client.call("ranking", edition=LAUSANNE, slug=LAUSANNE_MEN, count=200, page=1)
    assert gender.table is not None

    ranked_gender, withdrawn_gender = split_ranked_and_withdrawn(gender.rows)
    assert ranked_gender, "expected finishers on the men's gender list"
    assert withdrawn_gender == [], (
        "men's DNFs were only visible on age-group lists during the 2026 capture; "
        "do not rely on the gender list alone"
    )
