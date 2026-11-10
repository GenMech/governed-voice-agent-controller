import httpx

from controller.governance import Governance
from controller.store import Store
from controller.strategy import Candidate


class FakeApi:
    def __init__(self):
        self.approvals = []
        self.current_version = 1
        self.applies = 0
        self.fail_stale_post = False

    def request(self, method, path, **kwargs):
        if path == "/approvals" and method == "POST":
            if self.fail_stale_post:
                request = httpx.Request("POST", "http://test/approvals")
                response = httpx.Response(409, request=request, json={"code": "stale_base_version"})
                raise httpx.HTTPStatusError("stale", request=request, response=response)
            body = kwargs["json"]
            approval = {**body, "approval_id": "apr_1", "status": "pending"}
            self.approvals.append(approval)
            return approval
        if path.startswith("/approvals?"):
            return self.approvals
        if path == "/approvals/apr_1":
            return self.approvals[0]
        if path == "/workflows/w/config":
            return {"version": self.current_version, "config": {}}
        if path == "/workflows/w/apply":
            self.applies += 1
            self.current_version += 1
            return {"version": self.current_version}
        if path == "/workflows/w/config/history":
            return []
        raise AssertionError((method, path))


def candidate():
    return Candidate("voice", {"allocations": {"default": {"voice": {"V1": 0.8, "V2": 0.2}}}},
                     "Test voice", "Reason", {"baseline_connected": 500}, 0.1, 100)


def test_pending_proposal_survives_restart_and_applies_once(tmp_path):
    api = FakeApi()
    db = tmp_path / "state.sqlite"
    wf = {"workflow_id": "w", "governance": {"auto_apply": {"enabled": False}, "approver_hours": [10, 19], "max_requests_per_24h": 3}}
    with Store(db) as store:
        gov = Governance(api, store)
        gov.propose(wf, {"version": 1, "config": {}}, candidate(), "2027-01-04T11:00:00+05:30")
        assert len(api.approvals) == 1
    api.approvals[0]["status"] = "approved"
    with Store(db) as store:
        gov = Governance(api, store)
        gov.reconcile("w", "2027-01-04T12:00:00+05:30")
        gov.reconcile("w", "2027-01-04T12:00:00+05:30")
        assert api.applies == 1
        assert store.active_intent("w") is None


def test_supervisor_version_prevents_stale_apply(tmp_path):
    api = FakeApi()
    wf = {"workflow_id": "w", "governance": {"auto_apply": {"enabled": False}, "approver_hours": [10, 19], "max_requests_per_24h": 3}}
    with Store(tmp_path / "state.sqlite") as store:
        gov = Governance(api, store)
        gov.propose(wf, {"version": 1, "config": {}}, candidate(), "2027-01-04T11:00:00+05:30")
        api.approvals[0]["status"] = "approved"
        api.current_version = 2
        gov.reconcile("w", "2027-01-04T12:00:00+05:30")
        assert api.applies == 0
        assert store.active_intent("w") is None


def test_approval_budget_blocks_extra_request(tmp_path):
    api = FakeApi()
    wf = {"workflow_id": "w", "governance": {"auto_apply": {"enabled": False}, "approver_hours": [10, 19], "max_requests_per_24h": 1}}
    with Store(tmp_path / "state.sqlite") as store:
        gov = Governance(api, store)
        gov.propose(wf, {"version": 1, "config": {}}, candidate(), "2027-01-04T11:00:00+05:30")
        first = store.active_intent("w")
        store.update_intent(first["proposal_id"], "rejected", "2027-01-04T12:00:00+05:30")
        gov.propose(wf, {"version": 1, "config": {}}, candidate(), "2027-01-04T18:00:00+05:30")
        assert len(api.approvals) == 1


def test_stale_submission_does_not_leave_prepared_intent_forever(tmp_path):
    api = FakeApi()
    api.fail_stale_post = True
    api.current_version = 2
    wf = {"workflow_id": "w", "governance": {"auto_apply": {"enabled": False}, "approver_hours": [10, 19], "max_requests_per_24h": 3}}
    with Store(tmp_path / "state.sqlite") as store:
        Governance(api, store).propose(wf, {"version": 1, "config": {}}, candidate(), "2027-01-04T11:00:00+05:30")
        assert store.active_intent("w") is None


def test_permitted_auto_apply_can_run_before_approver_hours(tmp_path):
    api = FakeApi()
    wf = {"workflow_id": "w", "governance": {"auto_apply": {"enabled": True, "allowed_dims": ["voice"], "max_shift": 0.2},
                                           "approver_hours": [10, 19], "max_requests_per_24h": 3}}
    change = candidate()
    change.dry_run["previous_weights"] = {"V1": 1}
    with Store(tmp_path / "state.sqlite") as store:
        assert Governance(api, store).can_propose(wf, "2027-01-04T09:00:00+05:30", candidate=change)
