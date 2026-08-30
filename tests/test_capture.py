from __future__ import annotations

import json

from capture.gate import is_active
from capture.harness import CaptureSession, select_contest_lists
from capture.report import analyse, render_markdown
from racedata.providers.datasport.parse import ListRef


class _Client:
    """Injectable transport that returns queued payloads per task/order."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.request_count = 0
        self.stage = None

    def call(self, task, *, edition=None, slug=None, order=None, count=None, page=None, **_):
        self.request_count += 1
        payload = self.responses.pop(0) if self.responses else {"table": {"rows": []}}

        class _R:
            def __init__(self, payload):
                self.payload = payload
                self.url = f"https://x/api?task={task}&slug={slug or ''}&order={order or ''}"
                self.stage = payload.get("stage")

        return _R(payload)


def _ranking(rows, *, stage="live", refreshwait=15000, sorting=None):
    payload = {
        "stage": stage,
        "refreshwait": refreshwait,
        "table": {"rows": rows, "totalrowcount": len(rows)},
    }
    if sorting is not None:
        payload["filter"] = [{"title": "Sorting", "values": sorting}]
    return payload


def _row(name, rank=None, time_text="", slug=None):
    row = {"name": {"text": name}, "target": {"task": "participant", "slug": slug or name.lower()}}
    if rank is not None:
        row["rank.main"] = rank
    if time_text:
        row["time.main"] = {"text": time_text}
    return row


# -- Gate -------------------------------------------------------------------------------
def test_gate_skips_a_finished_event():
    client = _Client([{"stage": "done", "table": {"rows": []}}])
    active, reason = is_active("zof-2025", client=client)
    assert active is False
    assert "final" in reason


def test_gate_captures_a_pre_race_event_to_get_a_baseline():
    client = _Client([{"stage": "reg", "table": {"rows": []}}])
    active, _ = is_active("zof-2026", client=client)
    assert active is True


def test_gate_captures_an_unrecognised_stage():
    """An unknown stage is itself a finding, so it must not be silently skipped."""
    client = _Client([{"stage": "some-new-thing", "table": {"rows": []}}])
    active, reason = is_active("x", client=client)
    assert active is True
    assert "some-new-thing" in reason


def test_gate_fails_open_when_the_stage_cannot_be_read():
    """A wasted pass is cheaper than a missed race that cannot be repeated."""

    class _Broken:
        request_count = 0

        def call(self, *a, **k):
            from racedata.providers.datasport.client import DatasportRequestError

            raise DatasportRequestError("boom")

    active, reason = is_active("x", client=_Broken())
    assert active is True
    assert "capturing anyway" in reason


# -- Harness ----------------------------------------------------------------------------
def test_frames_are_deduplicated_on_content(tmp_path):
    payload = _ranking([_row("A", 1, "1:00,0")], sorting=[])
    session = CaptureSession(
        "zof", output_dir=tmp_path, client=_Client([payload, payload, payload, payload])
    )

    first = session.run_pass()
    second = session.run_pass()

    assert first.frames_written > 0
    assert second.frames_written == 0
    assert second.frames_unchanged > 0


def test_volatile_fields_do_not_count_as_a_change(tmp_path):
    """The refresh nonce and tracking beacon rotate on every request. Hashing them would
    make every pass look like new data and bloat the corpus without adding information."""
    first = _ranking([_row("A", 1, "1:00,0")], sorting=[])
    first["refresh"] = "refresh=aaaa"
    second = _ranking([_row("A", 1, "1:00,0")], sorting=[])
    second["refresh"] = "refresh=bbbb"
    second["gtag"] = {"id": "rotating"}

    session = CaptureSession(
        "zof", output_dir=tmp_path, client=_Client([first, first, second, second])
    )
    session.run_pass()
    again = session.run_pass()

    assert again.frames_written == 0


def test_a_real_content_change_is_captured(tmp_path):
    before = _ranking([_row("A", 1, "1:00,0")], sorting=[])
    after = _ranking([_row("A", 1, "1:00,0"), _row("B", 2, "1:05,0")], sorting=[])

    session = CaptureSession(
        "zof", output_dir=tmp_path, client=_Client([before, before, after, after])
    )
    session.run_pass()
    second = session.run_pass()

    assert second.frames_written > 0


def test_manifest_survives_a_restart(tmp_path):
    payload = _ranking([_row("A", 1, "1:00,0")], sorting=[])
    CaptureSession("zof", output_dir=tmp_path, client=_Client([payload, payload])).run_pass()

    # A fresh session, as a new scheduled run would be.
    resumed = CaptureSession("zof", output_dir=tmp_path, client=_Client([payload, payload]))

    assert resumed.run_pass().frames_written == 0


def test_a_blocked_request_is_recorded_as_an_error_not_a_crash(tmp_path):
    class _Blocked:
        request_count = 0

        def call(self, *a, **k):
            from racedata.providers.datasport.client import DatasportBlockedError

            raise DatasportBlockedError("error code: 1010")

    session = CaptureSession("zof", output_dir=tmp_path, client=_Blocked())

    summary = session.run_pass()

    assert any("BLOCKED" in message for message in summary.errors)


def test_select_contest_lists_matches_a_prefix_and_its_sub_contests():
    refs = [
        ListRef("a", "Men", "gender", "Zofingen 5000"),
        ListRef("b", "U16", "agegroup", "Zofingen 5000 - U16"),
        ListRef("c", "Men", "gender", "World Triathlon Long Distance - AGE GROUPS"),
    ]

    selected = select_contest_lists(refs, ("Zofingen 5000",))

    assert [ref.slug for ref in selected] == ["a", "b"]


def test_select_contest_lists_with_no_prefix_returns_everything():
    refs = [ListRef("a", "Men", "gender", "Zofingen 5000")]

    assert select_contest_lists(refs, ()) == refs


# -- Report -----------------------------------------------------------------------------
def _write_corpus(tmp_path, passes):
    session_client = _Client([item for pair in passes for item in pair])
    session = CaptureSession("zof", output_dir=tmp_path, client=session_client)
    for _ in passes:
        session.run_pass()
    return tmp_path


def test_report_answers_the_withdrawal_question_when_it_is_observed(tmp_path):
    """The case a finished race cannot contain: ranked at a checkpoint, withdrawn later."""
    ranked = _ranking([_row("Ann", 1, "1:00,0"), _row("Bob", 2, "1:05,0")], sorting=[])
    withdrew = _ranking(
        [_row("Ann", 1, "1:00,0"), {"separator": {"text": "Did not finish"}}, _row("Bob")],
        sorting=[],
    )
    _write_corpus(tmp_path, [(ranked, ranked), (withdrew, withdrew)])

    findings = analyse(tmp_path, edition="zof")

    assert any(item["athlete"] == "bob" for item in findings.ranked_then_withdrawn)
    assert "Yes" in render_markdown(findings)


def test_report_is_explicit_when_a_question_is_unanswered(tmp_path):
    """"We did not see it" must never be presented as "it does not happen"."""
    payload = _ranking([_row("Ann", 1, "1:00,0")], stage="reg", sorting=[])
    _write_corpus(tmp_path, [(payload, payload)])

    findings = analyse(tmp_path, edition="zof")
    markdown = render_markdown(findings)

    assert findings.in_race_stage == "not observed"
    assert findings.ranked_then_withdrawn == []
    assert "Do not treat this as proof" in markdown


def test_report_detects_a_revised_time(tmp_path):
    first = _ranking([_row("Ann", 1, "1:00,0")], sorting=[])
    revised = _ranking([_row("Ann", 1, "1:00,9")], sorting=[])
    _write_corpus(tmp_path, [(first, first), (revised, revised)])

    findings = analyse(tmp_path, edition="zof")

    assert findings.revised_times
    assert findings.revised_times[0]["was"] == "1:00,0"
    assert findings.revised_times[0]["now"] == "1:00,9"


def test_report_records_the_in_race_stage_and_refresh_wait(tmp_path):
    payload = _ranking([_row("Ann", 1, "1:00,0")], stage="idle", refreshwait=15000, sorting=[])
    _write_corpus(tmp_path, [(payload, payload)])

    findings = analyse(tmp_path, edition="zof")

    assert findings.in_race_stage == "idle"
    assert findings.refresh_wait_values_ms == [15000]


def test_report_on_an_empty_corpus_says_so_rather_than_looking_healthy(tmp_path):
    findings = analyse(tmp_path, edition="zof")

    assert findings.frames == 0
    assert any("no frames" in message for message in findings.errors)
    assert "Capture errors" in render_markdown(findings)


def test_findings_are_json_serialisable(tmp_path):
    payload = _ranking([_row("Ann", 1, "1:00,0")], sorting=[])
    _write_corpus(tmp_path, [(payload, payload)])

    findings = analyse(tmp_path, edition="zof")

    assert json.dumps(vars(findings), default=str)
