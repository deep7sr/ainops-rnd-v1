"""The case books: the Postgres store keeps exactly the rules of the in-memory one (CaseBook).

Every rule test runs on both: `memory` always, `postgres` only with `pytest -m postgres` (the
test database, TEST_DATABASE_URL). The copy from Neo4j is tested between two in-memory books.
"""

import threading
from collections.abc import Iterator

import pytest
from test_cases import FAULT, HEALTHY, MemoryCases, _case

from ainops.case_store import CaseBook, Neo4jCases, PostgresCases, copy_cases
from ainops.cases import Case, ReviewRequest, review_case
from ainops.config import Settings
from ainops.db import Database

BOOKS = [
    pytest.param("memory"),
    pytest.param("postgres", marks=pytest.mark.postgres),
]


@pytest.fixture(params=BOOKS)
def book(request: pytest.FixtureRequest) -> Iterator[CaseBook]:
    if request.param == "memory":
        yield MemoryCases()
        return
    database = Database(request.getfixturevalue("postgres_url"), max_size=4)
    try:
        yield PostgresCases(database)
    finally:
        database.close()


def _drafted(run_id: str = "inv-abc123", healthy: bool = False) -> Case:
    events = (HEALTHY if healthy else FAULT)["events"]
    case = _case(events, by_hand=healthy)
    assert case is not None
    return case.model_copy(update={"id": run_id.replace("inv-", "case-"), "run_id": run_id})


def _at(case: Case, when: str) -> Case:
    return case.model_copy(update={"created_at": when, "updated_at": when})


def _reviewed(case: Case, reviewer: str = "D") -> Case:
    return review_case(case, ReviewRequest(action="approve", reviewer=reviewer))


def test_a_case_comes_back_exactly_as_saved(book: CaseBook) -> None:
    case = _drafted()
    assert book.save(case) is True
    assert book.get(case.id) == case
    assert book.for_run(case.run_id) == case
    assert book.get("case-nope") is None
    assert book.for_run("inv-nope") is None


def test_lists_newest_first_with_counts_and_statuses(book: CaseBook) -> None:
    older = _at(_drafted("inv-older1"), "2026-10-01T10:00:00+00:00")
    newer = _at(_drafted("inv-newer1", healthy=True), "2026-10-02T10:00:00+00:00")
    book.save(older)
    book.save(newer)
    assert [c.id for c in book.all()] == ["case-newer1", "case-older1"]
    book.save(_reviewed(older), only_if="pending")  # a review makes it the latest change
    assert [c.id for c in book.all()] == ["case-older1", "case-newer1"]
    assert [c.id for c in book.all("approved")] == ["case-older1"]
    assert book.all("rejected") == []
    assert book.counts() == {"pending": 1, "approved": 1, "rejected": 0}
    assert book.statuses(["inv-older1", "inv-newer1", "inv-nope"]) == {
        "inv-older1": "approved",
        "inv-newer1": "pending",
    }
    assert book.statuses([]) == {}


def test_a_reviewed_case_is_not_overwritten(book: CaseBook) -> None:
    case = _drafted()
    book.save(case)
    approved = _reviewed(case)
    assert book.save(approved, only_if="pending") is True
    later_draft = case.model_copy(update={"question": "changed"})
    assert book.save(later_draft, only_if="pending") is False  # still approved: nothing written
    assert book.get(case.id) == approved
    assert book.save(later_draft) is True  # without only_if a save always writes
    assert book.get(case.id) == later_draft


def test_a_new_case_is_saved_even_with_only_if(book: CaseBook) -> None:
    case = _drafted()
    assert book.save(case, only_if="pending") is True
    assert book.get(case.id) == case


@pytest.mark.postgres
def test_two_reviews_at_the_same_moment_only_one_wins(postgres_url: str) -> None:
    """Both read the case while pending; both save with only_if="pending" at once."""
    database = Database(postgres_url, max_size=4)
    try:
        book = PostgresCases(database)
        case = _drafted()
        book.save(case)
        start = threading.Barrier(2)
        results: dict[str, bool] = {}

        def review(reviewer: str) -> None:
            reviewed = _reviewed(case, reviewer)
            start.wait()
            results[reviewer] = book.save(reviewed, only_if="pending")

        threads = [threading.Thread(target=review, args=(name,)) for name in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results.values()) == [False, True]
        winner = next(name for name, won in results.items() if won)
        stored = book.get(case.id)
        assert stored is not None and stored.review is not None
        assert stored.review.reviewer == winner
    finally:
        database.close()


@pytest.mark.parametrize(("setting", "kind"), [("postgres", PostgresCases), ("neo4j", Neo4jCases)])
def test_the_api_uses_the_store_the_setting_names(
    monkeypatch: pytest.MonkeyPatch, setting: str, kind: type
) -> None:
    from ainops.api import app as module

    class Graph:
        driver = object()

    monkeypatch.setattr(module, "settings", Settings(cases_store=setting))
    monkeypatch.setattr(module, "database", lambda: object())
    monkeypatch.setattr(module, "store", lambda: Graph())
    assert type(module.cases()) is kind


def test_copy_takes_what_is_missing_and_never_overwrites() -> None:
    source, target = MemoryCases(), MemoryCases()
    first, second, third = _drafted("inv-first1"), _drafted("inv-second1"), _drafted("inv-third1")
    for case in (first, second, third):
        source.save(case)
    target.save(second)  # already copied
    target.save(_reviewed(third))  # copied, then reviewed in Postgres
    done = copy_cases(source, target)
    assert done == {
        "copied": ["case-first1"],
        "same": ["case-second1"],
        "different": ["case-third1"],
    }
    assert target.get("case-third1") == _reviewed(third)  # the review in Postgres is kept
    assert source.cases.keys() == {"case-first1", "case-second1", "case-third1"}  # nothing deleted
    assert copy_cases(source, target)["copied"] == []  # running it again copies nothing
