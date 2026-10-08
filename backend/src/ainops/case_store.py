"""Where cases live: in Neo4j, next to the network they are about.

    (:Case {id, run_id, status, root_cause, devices, interfaces, updated_at, data})
        -[:INVOLVES {interfaces}]->(:Device)

`data` holds the whole case as JSON (cases.Case); the other properties are copies for queries.
Discovery keeps Device nodes (MERGE) and never deletes a Case; interfaces are rebuilt by every
discovery, so a case keeps interface names as text. If a device leaves the inventory, discovery
deletes it with its INVOLVES links, and the case still names it in `devices`.
"""

from typing import Protocol

from neo4j import Driver

from ainops.cases import Case

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
