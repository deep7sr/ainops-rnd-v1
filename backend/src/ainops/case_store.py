"""Where cases live: in Postgres, the system of record (docs/architecture-production.md).

    cases (id, run_id, status, made_by, root_cause, devices[], interfaces[], created_at,
           updated_at, data)            -- migrations/versions/0001_cases.py

`data` holds the whole case as JSON (cases.Case); the other columns are copies for queries.

Until phase 1 is checked, the old store is kept unchanged as the way back (CASES_STORE=neo4j):

    (:Case {id, run_id, status, root_cause, devices, interfaces, updated_at, data})
        -[:INVOLVES {interfaces}]->(:Device)

Both keep the same rule for reviews: with `only_if`, the case is stored only while its stored
status is still that, checked and written in one statement, so of two reviews sent at the same
moment only one can pass.
"""

from typing import Protocol

from neo4j import Driver

from ainops.cases import Case
from ainops.db import Database

SCHEMA = "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.id IS UNIQUE"


class CaseBook(Protocol):
    def get(self, case_id: str) -> Case | None: ...
    def for_run(self, run_id: str) -> Case | None: ...
    def all(self, status: str | None = None) -> list[Case]: ...
    def counts(self) -> dict[str, int]: ...
    def statuses(self, run_ids: list[str]) -> dict[str, str]: ...
    def save(self, case: Case, only_if: str | None = None) -> bool:
        """Store the case; with `only_if`, only while its stored status is still that."""
        ...


def copy_cases(source: CaseBook, target: CaseBook) -> dict[str, list[str]]:
    """Copy every case the target does not have yet (`ainops db copy-cases`). Safe to run again.

    Nothing is deleted from the source, and a case the target already has is never overwritten:
    it may have been reviewed there since. One that differs is listed so a person can look.
    """
    done: dict[str, list[str]] = {"copied": [], "same": [], "different": []}
    for case in source.all():
        there = target.get(case.id)
        if there is None:
            target.save(case)
            done["copied"].append(case.id)
        elif there.model_dump() == case.model_dump():
            done["same"].append(case.id)
        else:
            done["different"].append(case.id)
    return done


class PostgresCases:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _cases(self, query: str, **params: object) -> list[Case]:
        rows = self.db.rows(query, params)
        return [Case.model_validate(r["data"]) for r in rows]

    def get(self, case_id: str) -> Case | None:
        found = self._cases("SELECT data FROM cases WHERE id = %(id)s", id=case_id)
        return found[0] if found else None

    def for_run(self, run_id: str) -> Case | None:
        found = self._cases("SELECT data FROM cases WHERE run_id = %(run)s", run=run_id)
        return found[0] if found else None

    def all(self, status: str | None = None) -> list[Case]:
        return self._cases(
            """
            SELECT data FROM cases WHERE %(status)s::text IS NULL OR status = %(status)s
            ORDER BY updated_at DESC
            """,
            status=status,
        )

    def counts(self) -> dict[str, int]:
        rows = self.db.rows("SELECT status, count(*) AS n FROM cases GROUP BY status")
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        counts.update({str(r["status"]): int(r["n"]) for r in rows})
        return counts

    def statuses(self, run_ids: list[str]) -> dict[str, str]:
        rows = self.db.rows(
            "SELECT run_id, status FROM cases WHERE run_id = ANY(%(runs)s)", {"runs": run_ids}
        )
        return {str(r["run_id"]): str(r["status"]) for r in rows}

    def save(self, case: Case, only_if: str | None = None) -> bool:
        # A new case is stored as it is; an existing one only while its status is still
        # `only_if`. ON CONFLICT locks the row, so the check and the write are one step.
        rows = self.db.rows(
            """
            INSERT INTO cases (id, run_id, status, made_by, root_cause, devices, interfaces,
                               created_at, updated_at, data)
            VALUES (%(id)s, %(run_id)s, %(status)s, %(made_by)s, %(root_cause)s, %(devices)s,
                    %(interfaces)s, %(created_at)s, %(updated_at)s, %(data)s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                run_id = EXCLUDED.run_id, status = EXCLUDED.status, made_by = EXCLUDED.made_by,
                root_cause = EXCLUDED.root_cause, devices = EXCLUDED.devices,
                interfaces = EXCLUDED.interfaces, created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at, data = EXCLUDED.data
            WHERE %(only_if)s::text IS NULL OR cases.status = %(only_if)s
            RETURNING id
            """,
            {
                "id": case.id,
                "run_id": case.run_id,
                "status": case.status,
                "made_by": case.made_by,
                "root_cause": case.root_cause,
                "devices": case.draft.devices,
                "interfaces": case.draft.interfaces,
                "created_at": case.created_at,
                "updated_at": case.updated_at,
                "data": case.model_dump_json(),
                "only_if": only_if,
            },
        )
        return bool(rows)


class Neo4jCases:
    def __init__(self, driver: Driver) -> None:
        self.driver = driver
        self._schema = False

    def _rows(self, query: str, **params: object) -> list[dict[str, object]]:
        records, _, _ = self.driver.execute_query(query, params)
        return [r.data() for r in records]

    def _cases(self, query: str, **params: object) -> list[Case]:
        return [Case.model_validate_json(str(r["data"])) for r in self._rows(query, **params)]

    def get(self, case_id: str) -> Case | None:
        found = self._cases("MATCH (c:Case {id: $id}) RETURN c.data AS data", id=case_id)
        return found[0] if found else None

    def for_run(self, run_id: str) -> Case | None:
        found = self._cases("MATCH (c:Case {run_id: $run}) RETURN c.data AS data", run=run_id)
        return found[0] if found else None

    def all(self, status: str | None = None) -> list[Case]:
        return self._cases(
            """
            MATCH (c:Case) WHERE $status IS NULL OR c.status = $status
            RETURN c.data AS data ORDER BY c.updated_at DESC
            """,
            status=status,
        )

    def counts(self) -> dict[str, int]:
        rows = self._rows("MATCH (c:Case) RETURN c.status AS status, count(c) AS n")
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        counts.update({str(r["status"]): int(str(r["n"])) for r in rows})
        return counts

    def statuses(self, run_ids: list[str]) -> dict[str, str]:
        rows = self._rows(
            "MATCH (c:Case) WHERE c.run_id IN $runs RETURN c.run_id AS run, c.status AS status",
            runs=run_ids,
        )
        return {str(r["run"]): str(r["status"]) for r in rows}

    def save(self, case: Case, only_if: str | None = None) -> bool:
        if not self._schema:
            self._rows(SCHEMA)
            self._schema = True
        # MERGE then check the stored status, in one statement: two reviews sent at the same
        # moment cannot both pass the check.
        rows = self._rows(
            """
            MERGE (c:Case {id: $id})
            ON CREATE SET c.status = coalesce($only_if, $status)
            WITH c WHERE $only_if IS NULL OR c.status = $only_if
            SET c.run_id = $run_id, c.status = $status, c.root_cause = $root_cause,
                c.devices = $devices, c.interfaces = $interfaces,
                c.created_at = $created_at, c.updated_at = $updated_at, c.data = $data
            WITH c
            OPTIONAL MATCH (c)-[old:INVOLVES]->()
            DELETE old
            RETURN count(DISTINCT c) AS saved
            """,
            id=case.id,
            run_id=case.run_id,
            status=case.status,
            only_if=only_if,
            root_cause=case.root_cause,
            devices=case.draft.devices,
            interfaces=case.draft.interfaces,
            created_at=case.created_at,
            updated_at=case.updated_at,
            data=case.model_dump_json(),
        )
        if not rows or not rows[0]["saved"]:
            return False
        self._rows(
            """
            MATCH (c:Case {id: $id})
            UNWIND $devices AS name
            MATCH (d:Device {name: name})
            MERGE (c)-[r:INVOLVES]->(d)
            SET r.interfaces = [i IN $interfaces WHERE i STARTS WITH name + ' '
                                | substring(i, size(name) + 1)]
            """,
            id=case.id,
            devices=case.draft.devices,
            interfaces=case.draft.interfaces,
        )
        return True
