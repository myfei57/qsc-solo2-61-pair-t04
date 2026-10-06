"""End to end tests for configurable chain endpoints and boot validation."""

from __future__ import annotations

import json
import tempfile
import unittest

from tunnelnet.chain.config import default_config, from_mapping
from tunnelnet.chain.validation import InvalidChain
from tunnelnet.console.server import ChainConfigurationError, Server
from tunnelnet.store import Store


CANONICAL = [
    "access",
    "environment",
    "ventilation",
    "fire",
    "patrol",
    "energy",
    "audit",
]
ALTERNATE = ["access", "environment", "fire", "ventilation", "energy", "patrol", "audit"]


def config_payload(stages: list[str], version: str, name: str = "tunnel-control") -> dict:
    base = default_config()
    return {
        "name": name,
        "version": version,
        "stages": stages,
        "required": sorted(base.required),
        "predecessors": {stage: list(values) for stage, values in base.predecessors.items()},
        "actions": base.actions,
        "note": f"version {version}",
    }


class ChainConsoleCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store.open(f"{self._tmp.name}/data")
        self.server = Server(self.store, web_dir="web")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, method: str, path: str, payload: dict | None = None, query: dict | None = None):
        response = self.server.dispatch(method, path, payload, query)
        body = response.body.decode("utf-8")
        parsed = json.loads(body) if response.content_type.startswith("application/json") else body
        return response.status, parsed

    def test_active_chain_and_versions_endpoints(self) -> None:
        status, chain = self.call("GET", "/api/chain")
        self.assertEqual(status, 200)
        self.assertEqual(chain["version"], "1")
        self.assertEqual([step["stage"] for step in chain["steps"]], CANONICAL)
        self.assertEqual(len(chain["digest"]), 12)

        status, versions = self.call("GET", "/api/chain/versions")
        self.assertEqual(status, 200)
        self.assertEqual(versions["active"]["version"], "1")
        self.assertEqual(len(versions["versions"]), 1)

    def test_cycle_pins_active_version_and_writes_chain_audit_rows(self) -> None:
        status, body = self.call(
            "POST",
            "/api/cycle",
            {
                "cabin_id": "cabin-1",
                "zone": "zone-1",
                "samples": [10.0, 20.0],
                "at": "t",
                "watts": 100.0,
            },
        )
        self.assertEqual(status, 200)
        ref = body["chain"]
        self.assertEqual(ref["version"], "1")
        self.assertTrue(body["cycle_id"].startswith("cycle-"))

        status, instances = self.call("GET", "/api/chain/instances")
        self.assertEqual(status, 200)
        self.assertEqual(instances["items"][0]["status"], "completed")
        self.assertEqual(instances["items"][0]["chain"]["digest"], ref["digest"])

        status, audit = self.call("GET", "/api/audit")
        self.assertEqual(status, 200)
        for item in audit["items"]:
            self.assertEqual(item["chain_id"], "tunnel-control@1")
            self.assertEqual(item["cycle_id"], body["cycle_id"])

        status, replay = self.call(
            "GET", "/api/chain/replay", query={"cycle_id": [body["cycle_id"]]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(replay["stages"], CANONICAL)
        self.assertEqual(len(replay["audit_events"]), 4)

        status, query = self.call(
            "GET", "/api/audit/query", query={"chain_id": ["tunnel-control@1"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(query["for_chain"]), 4)
        status, query = self.call(
            "GET", "/api/audit/query", query={"cycle_id": [body["cycle_id"]]}
        )
        self.assertEqual(len(query["for_cycle"]), 4)

    def test_publish_is_idempotent_and_does_not_move_active(self) -> None:
        payload = config_payload(CANONICAL, version="1")
        status, first = self.call("POST", "/api/chain/publish", {"config": payload})
        self.assertEqual(status, 200)
        self.assertFalse(first["published"])
        status, versions = self.call("GET", "/api/chain/versions")
        self.assertEqual(len(versions["versions"]), 1)

    def test_invalid_publish_is_rejected_with_report(self) -> None:
        status, body = self.call(
            "POST",
            "/api/chain/publish",
            {"config": config_payload(["access", "audit"], version="broken")},
        )
        self.assertEqual(status, 400)
        self.assertIn("missing_stage", body["error"])

    def test_cycling_publish_is_rejected(self) -> None:
        cyclic = {
            "name": "tunnel-control",
            "version": "cyclic",
            "stages": ["access", "environment", "fire", "energy", "audit", "x", "y"],
            "required": ["access", "audit"],
            "predecessors": {"x": ["y"], "y": ["x"]},
        }
        status, body = self.call("POST", "/api/chain/publish", {"config": cyclic})
        self.assertEqual(status, 400)
        self.assertIn("cycle", body["error"])

    def test_activate_new_version_only_affects_later_cycles(self) -> None:
        # Start a cycle on v1, activate v2 while it is conceptually in flight;
        # pinning is captured at start, so the persisted instance stays on v1.
        first_instance = self.server.runtime.chains.start_cycle("cabin-1")

        status, body = self.call(
            "POST", "/api/chain/activate", {"config": config_payload(ALTERNATE, version="2")}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["activated"])

        status, chain = self.call("GET", "/api/chain")
        self.assertEqual(chain["version"], "2")
        self.assertEqual([step["stage"] for step in chain["steps"]], ALTERNATE)

        # old instance still resolves to the v1 definition
        status, replay = self.call(
            "GET", "/api/chain/replay", query={"cycle_id": [first_instance.id]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(replay["chain_id"], "tunnel-control@1")
        self.assertEqual(replay["stages"], CANONICAL)

        # the new cycle starts on v2
        status, body = self.call(
            "POST",
            "/api/cycle",
            {
                "cabin_id": "cabin-2",
                "zone": "zone-2",
                "samples": [1.0],
                "at": "t2",
                "watts": 5.0,
            },
        )
        self.assertEqual(body["chain"]["version"], "2")

        # replay by version returns every cycle on that version
        status, replayed = self.call(
            "GET", "/api/chain/replay", query={"chain_id": ["tunnel-control@1"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(replayed["items"]), 1)

    def test_activate_existing_version_by_id(self) -> None:
        self.call("POST", "/api/chain/publish", {"config": config_payload(ALTERNATE, version="3")})
        status, body = self.call(
            "POST", "/api/chain/activate", {"chain_id": "tunnel-control@3"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["ref"]["version"], "3")
        status, body = self.call("POST", "/api/chain/activate", {"chain_id": "missing@x"})
        self.assertEqual(status, 400)

    def test_same_version_changed_content_is_rejected(self) -> None:
        self.call("POST", "/api/chain/activate", {"config": config_payload(ALTERNATE, version="4")})
        status, body = self.call(
            "POST", "/api/chain/publish", {"config": config_payload(CANONICAL, version="4")}
        )
        self.assertEqual(status, 400)
        self.assertIn("already exists with different content", body["error"])

    def test_replay_requires_parameters(self) -> None:
        status, body = self.call("GET", "/api/chain/replay")
        self.assertEqual(status, 400)
        status, body = self.call("GET", "/api/chain/replay", query={"cycle_id": ["ghost"]})
        self.assertEqual(status, 404)

    def test_history_retained_across_restart(self) -> None:
        self.call("POST", "/api/chain/activate", {"config": config_payload(ALTERNATE, version="2")})
        restarted = Server(self.store, web_dir="web")
        status, versions = self._call(restarted, "GET", "/api/chain/versions")
        self.assertEqual(status, 200)
        self.assertEqual(len(versions["versions"]), 2)
        self.assertEqual(versions["active"]["version"], "2")
        # booting again with the default config must not clobber the pointer
        self.assertEqual(
            self._call(restarted, "GET", "/api/chain")[1]["version"], "2"
        )

    def test_boot_refuses_invalid_configured_chain(self) -> None:
        invalid = from_mapping(config_payload(["access"], version="x"))
        with tempfile.TemporaryDirectory() as fresh:
            fresh_store = Store.open(f"{fresh}/data")
            with self.assertRaises(ChainConfigurationError) as raised:
                Server(fresh_store, web_dir="web", chain_config=invalid)
            message = str(raised.exception)
            self.assertIn("missing_stage", message)
            self.assertIn("tunnel-control@x", message)
            # the underlying cause is the assembly failure
            self.assertIsInstance(raised.exception.__cause__, InvalidChain)
            # a refused boot leaves no active pointer and no chain documents
            from tunnelnet.chain import ChainManager

            self.assertIsNone(ChainManager(fresh_store).active_ref())
            self.assertEqual(fresh_store.kinds(), [])

    def _call(self, server: Server, method: str, path: str):
        response = server.dispatch(method, path)
        return response.status, json.loads(response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
