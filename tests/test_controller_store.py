import json

from controller.store import Store


def test_chunk_ingest_is_atomic_and_idempotent(tmp_path):
    db = tmp_path / "state.sqlite"
    events = [
        {"type": "call", "event_id": 1, "ts": "2027-01-04T10:00:00+05:30", "workflow_id": "w",
         "config_version": 1, "cohort_id": "default", "variant": {"voice": "V1", "welcome_message": "W1", "caller_id": "D1", "prompt_version": "P1"},
         "connected": True, "engaged": False, "qa": {"hallucination_flag": True}},
        {"type": "call", "event_id": 2, "ts": "2027-01-04T10:15:00+05:30", "workflow_id": "w",
         "config_version": 1, "cohort_id": "default", "variant": {"voice": "V1", "welcome_message": "W1", "caller_id": "D1", "prompt_version": "P1"},
         "connected": False, "engaged": False, "qa": None},
    ]
    lines = [json.dumps(x) for x in events]
    with Store(db) as store:
        assert store.ingest_chunk(3, lines)
        assert not store.ingest_chunk(3, lines)
        assert store.last_chunk() == 3
        assert store.counts("w", "voice", "V1") == (2, 1, 0, 1)
    with Store(db) as store:
        assert store.last_chunk() == 3
        assert store.counts("w", "voice", "V1") == (2, 1, 0, 1)


def test_failed_chunk_does_not_advance_cursor(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        try:
            store.ingest_chunk(0, ['{"type":"call"}', "not-json"])
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError("malformed chunk accepted")
        assert store.last_chunk() == -1


def test_variant_query_can_exclude_explicit_cohorts(tmp_path):
    base = {"type": "call", "ts": "2027-01-04T10:00:00+05:30", "workflow_id": "w", "config_version": 1,
            "connected": True, "engaged": True, "qa": None}
    default = {**base, "cohort_id": "default", "variant": {"voice": "V1"}}
    senior = {**base, "cohort_id": "senior", "variant": {"voice": "V2"}}
    with Store(tmp_path / "state.sqlite") as store:
        store.ingest_chunk(0, [json.dumps(default), json.dumps(senior)])
        assert store.variants("w", "voice", cohort="default") == {"V1": (1, 1, 1, 0)}
