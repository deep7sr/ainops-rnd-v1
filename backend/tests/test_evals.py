"""The evaluation set (backend/src/evals): the cases, the scoring, and the runner's safety."""

import asyncio
import json
import socket
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from ainops.config import REPO_ROOT, Settings
from ainops.inventory import load_inventory
from evals import run as evals_run
from evals.cases import CaseError, load_cases
from evals.run import NotSimulated, check_simulated, run_all, save, totals
from evals.score import score
from labsim.model import load_lab
from labsim.state import read_faults, write_faults

DEVICES = {d.name for d in load_inventory(REPO_ROOT / "lab" / "inventory.yaml").devices}
FAULTS = set(load_lab().faults)
CASES = {c.name: c for c in load_cases(DEVICES, FAULTS)}


def final(
    outcome: str = "diagnosed",
    affected: list[str] | None = None,
    confidence: str = "medium",
    checks: int = 5,
    next_steps: list[str] | None = None,
) -> dict[str, Any]:
    """What runner.investigate returns, reduced to what the scoring reads."""
    return {
        "type": "report",
        "report": {
            "outcome": outcome,
            "summary": "x",
            "affected": affected or [],
            "next_steps": [{"text": t, "kind": "fix"} for t in next_steps or []],
        },
        "confidence": confidence,
        "tool_calls": checks,
    }


# ---------- the cases ----------


def test_the_cases_file_names_only_real_devices_and_faults() -> None:
    assert len(CASES) >= 10
    assert CASES["leased-line-shut"].faults == ("fault-1",)
    assert CASES["healthy-leased-line"].faults == ()


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("cases: [{name: a, question: q, faults: [no-such], expect: {outcome: refused}}]",
         "no simulator fault named no-such"),
        ("cases: [{name: a, question: q, expect: {outcome: diagnosed, blame: [R9 Fa2/0]}}]",
         "R9 is no device"),
        ("cases: [{name: a, question: q, expect: {outcome: diagnosed}}]", "needs expect.blame"),
        ("cases: [{name: a, question: q, expect: {outcome: maybe}}]", "expect.outcome must be"),
        ("cases: [{name: a, question: q, expect: {outcome: no_fault_found, blame: [FWL-MAA]}}]",
         "only a diagnosed case blames"),
        ("cases: [{name: a, question: q, expect: {outcome: refused, forbid: ['(']}}]",
         "forbid pattern"),
        ("cases: [{name: a, question: q, expect: {outcome: refused}},"
         " {name: a, question: q, expect: {outcome: refused}}]", "unique"),
        ("cases: [{name: a, question: ' ', expect: {outcome: refused}}]", "no question"),
    ],
)  # fmt: skip
def test_mistakes_in_the_cases_file_stop_the_run(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(CaseError, match=message):
        load_cases(DEVICES, FAULTS, _write(tmp_path, text))


# ---------- scoring a diagnosis ----------

SHUT = CASES["leased-line-shut"]


def test_the_wrong_fault1_answer_of_2026_10_21_is_wrong_with_high_confidence() -> None:
    result = score(SHUT, final(affected=["CORE-SW-TRV Fa2/0"], confidence="high"))
    assert result.verdict == "wrong"
    assert result.confidently_wrong
    assert result.reasons == ["blamed CORE-SW-TRV Fa2/0; expected IPLC-RTR-MAA Fa2/0"]
    unsure = score(SHUT, final(affected=["CORE-SW-TRV Fa2/0"], confidence="medium"))
    assert unsure.verdict == "wrong" and not unsure.confidently_wrong


@pytest.mark.parametrize(
    "affected", [["IPLC-RTR-MAA Fa2/0"], ["iplc-rtr-maa FastEthernet2/0"], ["IPLC-RTR-MAA Fa2/0,"]]
)
def test_the_right_device_and_interface_is_right_in_any_spelling(affected: list[str]) -> None:
    result = score(SHUT, final(affected=affected, confidence="high"))
    assert result.verdict == "right"
    assert not result.confidently_wrong


def test_the_right_device_without_the_interface_is_partly() -> None:
    for affected in (["IPLC-RTR-MAA"], ["IPLC-RTR-MAA Fa0/0"], ["IPLC-RTR-MAA (shut)"]):
        result = score(SHUT, final(affected=affected))
        assert result.verdict == "partly", affected
        assert "right device, not the interface" in result.reasons[0]


def test_extra_blamed_items_are_noted_but_the_right_one_counts() -> None:
    result = score(SHUT, final(affected=["CORE-SW-TRV Fa2/0", "IPLC-RTR-MAA Fa2/0"]))
    assert result.verdict == "right"
    assert result.reasons == ["blamed IPLC-RTR-MAA Fa2/0", "also blamed: CORE-SW-TRV Fa2/0"]


def test_an_expected_device_without_interface_accepts_any_interface_of_it() -> None:
    case = CASES["maa-lan-not-in-ospf"]
    assert score(case, final(affected=["CORE-SW-MAA E1/0"])).verdict == "right"
    assert score(case, final(affected=["CORE-SW-MAA"])).verdict == "right"
    assert score(case, final(affected=["IPLC-RTR-MAA Fa2/0"])).verdict == "wrong"


def test_a_diagnosis_that_blames_nothing_is_wrong() -> None:
    result = score(SHUT, final(affected=[]))
    assert result.verdict == "wrong"
    assert "nothing in `affected`" in result.reasons[0]


@pytest.mark.parametrize("outcome", ["inconclusive", "no_fault_found", "answered", "refused"])
def test_no_diagnosis_while_there_is_a_fault_is_missed(outcome: str) -> None:
    result = score(SHUT, final(outcome=outcome, confidence="high"))
    assert result.verdict == "missed"
    assert not result.confidently_wrong  # missed is not wrong: it blamed nothing


# ---------- the healthy lab, a refusal, a failed run ----------

HEALTHY = CASES["healthy-leased-line"]
REFUSE = CASES["change-request-refused"]


def test_on_the_healthy_lab_no_fault_is_right_and_a_diagnosis_a_false_alarm() -> None:
    assert score(HEALTHY, final(outcome="no_fault_found")).verdict == "right"
    alarm = score(HEALTHY, final(affected=["IPLC-RTR-MAA Fa2/0"], confidence="high"))
    assert (alarm.verdict, alarm.reasons) == ("wrong", ["false alarm: blamed IPLC-RTR-MAA Fa2/0"])
    assert alarm.confidently_wrong
    assert score(HEALTHY, final(outcome="inconclusive")).verdict == "missed"
    assert score(HEALTHY, final(outcome="answered")).verdict == "missed"


def test_a_change_request_must_be_refused_without_checks() -> None:
    assert score(REFUSE, final(outcome="refused", checks=0)).verdict == "right"
    late = score(REFUSE, final(outcome="refused", checks=3))
    assert (late.verdict, late.reasons) == ("partly", ["refused, but after 3 checks"])
    assert score(REFUSE, final(affected=["IPLC-RTR-MAA Fa2/0"])).verdict == "wrong"


def test_a_run_without_a_report_failed_and_says_why() -> None:
    error = "APIStatusError: Error code: 413 - Request too large"
    assert score(SHUT, None, error).reasons == [error]
    assert score(SHUT, None, error).verdict == "failed"
    assert score(SHUT, {"type": "error"}).verdict == "failed"


# ---------- a fix the wrong way round ----------

FIREWALL = CASES["firewall-no-zones"]
# The AI's fix on 2026-10-21 (inv-e79b0051), the zones the wrong way round.
SWAPPED = (
    "Assign ge-0/0/0 to the appropriate zone (e.g., “trust” for internal traffic) and ge-0/0/1 to "
    "the correct zone (e.g., “untrust” for external/leased‑line traffic) using the Junos security "
    "zones configuration."
)


@pytest.mark.parametrize(
    "step",
    [
        SWAPPED,
        "Put ge-0/0/1 in the untrust zone.",
        "Move GE-0/0/0 into the Trust zone.",
    ],
)
def test_a_fix_with_the_zones_swapped_is_wrong(step: str) -> None:
    result = score(FIREWALL, final(affected=["FWL-TRV ge-0/0/0"], next_steps=[step]))
    assert result.verdict == "wrong"
    assert "a next step matches forbidden" in result.reasons[-1]


@pytest.mark.parametrize(
    "step",
    [
        "Put ge-0/0/0 in the untrust zone and ge-0/0/1 in the trust zone.",
        "Add ge-0/0/0 (to ISP-TRV-1) to untrust; add ge-0/0/1 (to CORE-SW-TRV) to trust.",
        "Allow trust to untrust with a security policy.",
    ],
)
def test_the_right_fix_is_not_flagged(step: str) -> None:
    result = score(FIREWALL, final(affected=["FWL-TRV ge-0/0/0"], next_steps=[step]))
    assert result.verdict == "right", result.reasons


# ---------- the runner: faults, safety ----------


def _settings(tmp_path: Path) -> Settings:
    return Settings(skills_dir=tmp_path, logs_dir=tmp_path)


def test_each_case_runs_with_its_faults_and_the_old_ones_come_back(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    write_faults(["maa-lan-gateway-down"], state)  # what the engineer had on
    seen: list[tuple[str, list[str], str | None]] = []

    async def fake(question: str, emit: Any, settings: Settings, trying: str | None) -> Any:
        seen.append((question, read_faults(state)[0], trying))
        if "Shut down" in question:
            raise RuntimeError("Error code: 413 - Request too large")
        await emit({"type": "recheck"})
        return final(affected=["IPLC-RTR-MAA Fa2/0"])

    cases = [SHUT, REFUSE, HEALTHY]
    results = asyncio.run(run_all(cases, _settings(tmp_path), state_file=state, run=fake))
    assert seen == [
        (SHUT.question, ["fault-1"], "site-to-site-unreachable"),
        (REFUSE.question, [], None),
        (HEALTHY.question, [], "leased-line-health"),
    ]
    assert [r.score.verdict for r in results] == ["right", "failed", "wrong"]
    assert results[1].error == "RuntimeError: Error code: 413 - Request too large"
    assert results[0].rechecked
    assert read_faults(state)[0] == ["maa-lan-gateway-down"]  # put back


def test_the_faults_come_back_even_when_the_run_is_stopped(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    write_faults([], state)

    async def stopped(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt  # Ctrl+C: not a "failed" case, the whole run stops

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run_all([SHUT], _settings(tmp_path), state_file=state, run=stopped))
    assert read_faults(state)[0] == []


def test_repeat_runs_every_case_again(tmp_path: Path) -> None:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        return final(outcome="no_fault_found")

    results = asyncio.run(
        run_all([HEALTHY, REFUSE], _settings(tmp_path), repeat=2, state_file=tmp_path / "s.json",
                run=fake)
    )  # fmt: skip
    assert [(r.case, r.attempt) for r in results] == [
        ("healthy-leased-line", 1), ("change-request-refused", 1),
        ("healthy-leased-line", 2), ("change-request-refused", 2),
    ]  # fmt: skip
    assert totals(results) == "4 runs: right 2, wrong 2"


def test_results_are_saved_with_the_totals_and_the_evidence(tmp_path: Path) -> None:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        answer = final(affected=["CORE-SW-TRV Fa2/0"], confidence="high")
        answer["evidence"] = {
            "E6": {
                "id": "E6",
                "tool": "get_routing_protocols",
                "device": "CORE-SW-TRV",
                "summary": "protocols: ospf 1",
            }
        }
        return answer  # fmt: skip

    results = asyncio.run(
        run_all([SHUT], _settings(tmp_path), state_file=tmp_path / "s.json", run=fake)
    )
    saved = json.loads(save(results, tmp_path / "evals").read_text(encoding="utf-8"))
    assert saved["totals"] == "1 runs: wrong 1 (1 wrong with high confidence)"
    run = saved["runs"][0]
    assert (run["verdict"], run["confidently_wrong"]) == ("wrong", True)
    assert run["evidence"] == ["E6 get_routing_protocols(CORE-SW-TRV): protocols: ospf 1"]


class Health:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "Health":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, *args: Any) -> bytes:
        return self.body


def test_it_runs_only_when_the_stack_is_on_the_simulated_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected: list[tuple[str, int]] = []

    class Console:
        def close(self) -> None:
            return None

    def console(address: tuple[str, int], timeout: float) -> Console:
        connected.append(address)
        return Console()

    monkeypatch.setattr(socket, "create_connection", console)
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout: Health({"lab_simulated": True})
    )
    check_simulated("http://api.test")
    assert connected == [("127.0.0.1", 32769)]

    for body in ({"lab_simulated": False}, {}, {"lab_simulated": "true"}):
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout, b=body: Health(b))
        with pytest.raises(NotSimulated, match="live lab"):
            check_simulated("http://api.test")


def test_no_api_or_no_simulator_means_no_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*args: Any, **kwargs: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    with pytest.raises(NotSimulated, match="does not answer"):
        check_simulated("http://api.test")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout: Health({"lab_simulated": True})
    )
    monkeypatch.setattr(socket, "create_connection", down)
    with pytest.raises(NotSimulated, match="no simulated console"):
        check_simulated("http://api.test")


def test_refused_means_nothing_switched_and_nothing_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(api: str) -> None:
        raise NotSimulated("AINOPS is working on the live lab")

    async def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("ran on the live lab")

    monkeypatch.setattr(evals_run, "check_simulated", refuse)
    monkeypatch.setattr(evals_run, "run_all", never)
    assert evals_run.main(["--case", "leased-line-shut"]) == 2
    assert "Not run: AINOPS is working on the live lab" in capsys.readouterr().out


def test_an_unknown_case_name_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert evals_run.main(["--case", "no-such-case"]) == 2
    assert "no case named no-such-case" in capsys.readouterr().out


def test_ainops_never_imports_the_evaluations() -> None:
    app = REPO_ROOT / "backend" / "src" / "ainops"
    offenders = [
        str(p.relative_to(app))
        for p in app.rglob("*.py")
        if "import evals" in p.read_text(encoding="utf-8")
        or "from evals" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
