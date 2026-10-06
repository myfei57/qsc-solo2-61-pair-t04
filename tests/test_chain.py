"""Tests for configurable, versioned control chains."""

from __future__ import annotations

import json
import tempfile
import unittest

from tunnelnet.audit import Record
from tunnelnet.chain import (
    ChainCatalog,
    ChainConfig,
    ChainManager,
    InvalidChain,
    NoActiveChain,
    VersionExists,
    assemble,
    default_config,
    load_config,
    replay,
    validate,
)
from tunnelnet.chain.catalog import VersionMissing
from tunnelnet.chain.definition import ChainRef, compute_digest
from tunnelnet.store import Store
from tunnelnet.store import record as record_module


def stage_order(stages: list[str], **overrides: object) -> ChainConfig:
    base = default_config()
    return ChainConfig(
        name=str(overrides.get("name", base.name)),
        version=str(overrides.get("version", "99")),
        stages=tuple(stages),
        required=base.required,
        predecessors={} if overrides.get("drop_predecessors") else dict(base.predecessors),
        actions=dict(base.actions),
        note="test chain",
    )


CANONICAL_STAGES = [
    "access",
    "environment",
    "ventilation",
    "fire",
    "patrol",
    "energy",
    "audit",
]


class ValidationCase(unittest.TestCase):
    def test_default_chain_assembles(self) -> None:
        chain = assemble(default_config())
        self.assertEqual(chain.chain_id, "tunnel-control@1")
        self.assertEqual(chain.count(), 7)
        self.assertEqual(chain.stages, tuple(CANONICAL_STAGES))
        self.assertTrue(chain.before("access", "audit"))
        self.assertEqual(chain.last(), "audit")
        self.assertEqual(len(chain.digest), 12)

    def test_missing_required_stage_is_rejected(self) -> None:
        config = stage_order(["access", "environment", "audit"])
        report = validate(config)
        self.assertFalse(report.ok)
        codes = {error.code for error in report.errors}
        self.assertIn("missing_stage", codes)
        with self.assertRaises(InvalidChain) as raised:
            assemble(config)
        self.assertIn("missing_stage", str(raised.exception))

    def test_duplicate_stage_is_rejected(self) -> None:
        config = stage_order(CANONICAL_STAGES[:-1] + ["audit", "audit"])
        codes = {error.code for error in validate(config).errors}
        self.assertIn("duplicate_stage", codes)

    def test_order_violation_is_rejected(self) -> None:
        config = stage_order(list(reversed(CANONICAL_STAGES)))
        codes = {error.code for error in validate(config).errors}
        self.assertTrue({"order_violation", "cycle"} & codes)

    def test_cycle_in_predecessor_graph_is_rejected(self) -> None:
        config = load_config(
            json.dumps(
                {
                    "name": "looped",
                    "version": "1",
                    "stages": ["access", "environment", "fire", "energy", "audit", "x", "y"],
                    "required": ["access", "audit"],
                    "predecessors": {
                        "x": ["y"],
                        "y": ["x"],
                        "audit": ["energy", "fire", "environment", "access"],
                    },
                }
            )
        )
        codes = {error.code for error in validate(config).errors}
        self.assertIn("cycle", codes)

    def test_self_loop_is_rejected(self) -> None:
        config = load_config(
            json.dumps(
                {
                    "name": "looped",
                    "version": "1",
                    "stages": ["access", "audit"],
                    "required": ["access", "audit"],
                    "predecessors": {"audit": ["audit"]},
                }
            )
        )
        self.assertIn("self_loop", {error.code for error in validate(config).errors})

    def test_unknown_predecessor_reference(self) -> None:
        config = load_config(
            json.dumps(
                {
                    "name": "x",
                    "version": "1",
                    "stages": ["access", "audit"],
                    "required": ["access", "audit"],
                    "predecessors": {"audit": ["ghost"]},
                }
            )
        )
        self.assertIn("unknown_stage", {error.code for error in validate(config).errors})

    def test_tunnel_specific_order_is_allowed_when_invariants_hold(self) -> None:
        # A different tunnel swaps ventilation/fire ordering and patrol/energy;
        # access stays first, audit closes the chain, so it must assemble.
        order = ["access", "environment", "fire", "ventilation", "energy", "patrol", "audit"]
        chain = assemble(stage_order(order, name="other-tunnel", version="2"))
        self.assertEqual(chain.stages, tuple(order))

    def test_malformed_documents(self) -> None:
        with self.assertRaises(ValueError):
            load_config("{not json")
        with self.assertRaises(ValueError):
            load_config('["a", "b"]')
        with self.assertRaises(ValueError):
            load_config(json.dumps({"name": "x", "version": "1", "stages": []}))
        with self.assertRaises(ValueError):
            load_config(
                json.dumps({"name": "x", "version": "1", "stages": ["access", "audit"], "required": []})
            )


class CatalogCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog = ChainCatalog(Store.open(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_publish_is_idempotent_for_same_version(self) -> None:
        chain = assemble(default_config())
        self.assertTrue(self.catalog.publish(chain))
        self.assertFalse(self.catalog.publish(chain))
        self.assertEqual(self.catalog.versions(), ["tunnel-control@1"])

    def test_same_version_with_changed_content_is_rejected(self) -> None:
        first = assemble(stage_order(CANONICAL_STAGES, version="3"))
        self.catalog.publish(first)
        changed = assemble(stage_order(list(reversed(CANONICAL_STAGES))[::-1], version="3"))
        # reversed-twice is identical; make a genuinely different valid chain
        other_order = ["access", "environment", "fire", "ventilation", "patrol", "energy", "audit"]
        changed = assemble(stage_order(other_order, version="3"))
        with self.assertRaises(VersionExists):
            self.catalog.publish(changed)

    def test_full_history_is_retained(self) -> None:
        v1 = assemble(default_config())
        v2 = assemble(stage_order(CANONICAL_STAGES, version="2"))
        self.catalog.publish(v1)
        self.catalog.publish(v2)
        self.assertEqual(self.catalog.versions(), ["tunnel-control@1", "tunnel-control@2"])
        self.assertEqual(self.catalog.get("tunnel-control@1").digest, v1.digest)
        self.assertNotEqual(v1.digest, v2.digest)

    def test_cursor_activation(self) -> None:
        chain = assemble(default_config())
        self.assertIsNone(self.catalog.active_ref())
        with self.assertRaises(VersionMissing):
            self.catalog.set_active(chain)
        self.catalog.activate(chain)
        self.assertEqual(self.catalog.active_ref(), chain.ref)


class ManagerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = ChainManager(Store.open(f"{self._tmp.name}/data"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_bootstrap_activates_default_chain(self) -> None:
        chain, added = self.manager.bootstrap()
        self.assertTrue(added)
        self.assertEqual(self.manager.active().ref, chain.ref)
        # Repeated bootstrap with the same config is idempotent and preserves
        # the active pointer.
        again, added_again = self.manager.bootstrap(default_config())
        self.assertFalse(added_again)
        self.assertEqual(again.ref, chain.ref)

    def test_boot_refuses_invalid_chain(self) -> None:
        with self.assertRaises(InvalidChain):
            self.manager.bootstrap(stage_order(["access", "audit"]))
        with self.assertRaises(NoActiveChain):
            self.manager.active()

    def test_runtime_change_does_not_tear_running_cycle(self) -> None:
        first, _ = self.manager.bootstrap()
        instance = self.manager.start_cycle("cabin-1")
        self.assertEqual(instance.chain, first.ref)

        other_order = ["access", "environment", "fire", "ventilation", "energy", "patrol", "audit"]
        second, added = self.manager.activate(stage_order(other_order, version="2"))
        self.assertTrue(added)
        self.assertEqual(self.manager.active().ref, second.ref)

        # The running instance stays pinned to the old version ...
        pinned = self.manager.instance(instance.id)
        self.assertEqual(pinned.chain, first.ref)
        self.assertEqual(pinned.stages, first.stages)
        self.assertEqual(self.manager.chain_for_instance(instance.id).digest, first.digest)
        # ... while a newly started cycle uses the new one.
        later = self.manager.start_cycle("cabin-2")
        self.assertEqual(later.chain, second.ref)
        self.assertEqual(later.stages, second.stages)

    def test_finish_and_fail_close_instances(self) -> None:
        self.manager.bootstrap()
        instance = self.manager.start_cycle("cabin-1")
        closed = self.manager.finish_cycle(instance, {"ok": True})
        self.assertFalse(closed.is_open)
        self.assertEqual(closed.result, {"ok": True})
        other = self.manager.start_cycle("cabin-2")
        failed = self.manager.fail_cycle(other, "boom")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.result, {"error": "boom"})
        self.assertEqual(len(self.manager.open_instances()), 0)

    def test_state_survives_restart_and_old_version_replays(self) -> None:
        first, _ = self.manager.bootstrap()
        instance = self.manager.start_cycle("cabin-1")
        other_order = ["access", "environment", "fire", "ventilation", "energy", "patrol", "audit"]
        self.manager.activate(stage_order(other_order, version="2"))
        self.manager.finish_cycle(instance, {"last_stage": "audit"})

        restarted = ChainManager(Store.open(f"{self._tmp.name}/data"))
        self.assertEqual(restarted.active_ref(), self.manager.active_ref())
        replayed = restarted.instance(instance.id)
        self.assertEqual(replayed.chain, first.ref)
        chain = restarted.chain_for_instance(instance.id)
        self.assertEqual(chain.stages, first.stages)
        # full history survives, enabling old-version replay
        self.assertEqual(len(restarted.history()), 2)

    def test_publish_then_activate_existing_version(self) -> None:
        self.manager.bootstrap()
        order = ["access", "environment", "fire", "ventilation", "energy", "patrol", "audit"]
        version, added = self.manager.publish(stage_order(order, version="7"))
        self.assertTrue(added)
        # publish does not move the active pointer
        self.assertNotEqual(self.manager.active_ref(), version.ref)
        self.manager.activate_version(version.chain_id)
        self.assertEqual(self.manager.active_ref(), version.ref)
        with self.assertRaises(VersionMissing):
            self.manager.activate_version("nope@nope")

    def test_replay_filters_audit_rows_by_version_and_cycle(self) -> None:
        first, _ = self.manager.bootstrap()
        instance = self.manager.start_cycle("cabin-1")
        self.manager.finish_cycle(instance, {})
        rows = [
            Record(id="1", event="x", at="t", chain_id=first.chain_id, cycle_id=instance.id).as_dict(),
            Record(id="2", event="y", at="t", chain_id="other@9", cycle_id="other").as_dict(),
        ]
        result = replay(self.manager, instance.id, rows)
        self.assertEqual(result.chain_id, first.chain_id)
        self.assertTrue(result.matched)
        self.assertEqual([row["id"] for row in result.audit_events], ["1"])
        self.assertEqual(result.as_dict()["digest"], first.digest)


class RecordShapeCase(unittest.TestCase):
    def test_audit_record_omits_empty_chain_fields(self) -> None:
        self.assertEqual(
            Record(id="a", event="e", at="t").as_dict(),
            {"id": "a", "event": "e", "at": "t"},
        )
        full = Record(
            id="a",
            event="e",
            at="t",
            chain_id="c@1",
            chain_digest="deadbeef",
            cycle_id="cycle-1",
            stage="audit",
        ).as_dict()
        self.assertEqual(full["chain_id"], "c@1")
        self.assertEqual(full["stage"], "audit")

    def test_digest_is_content_based(self) -> None:
        first = assemble(stage_order(CANONICAL_STAGES, version="5"))
        same = assemble(stage_order(CANONICAL_STAGES, version="5"))
        other = assemble(stage_order(CANONICAL_STAGES, version="6"))
        self.assertEqual(first.digest, same.digest)
        self.assertNotEqual(first.digest, other.digest)
        self.assertEqual(
            compute_digest(first.canonical_document()), first.digest
        )

    def test_persisted_chain_document_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store.open(tmp)
            catalog = ChainCatalog(store)
            chain = assemble(default_config())
            catalog.publish(chain)
            document = store.load("chain", chain.chain_id)
            assert document is not None
            self.assertEqual(document["digest"], chain.digest)
            self.assertEqual(document["stages"], CANONICAL_STAGES)
            # documents are human readable JSON on disk
            path = record_module.record_path(tmp, "chain", chain.chain_id)
            with open(path, encoding="utf-8") as handle:
                decoded = json.load(handle)
            self.assertEqual(decoded["name"], "tunnel-control")
