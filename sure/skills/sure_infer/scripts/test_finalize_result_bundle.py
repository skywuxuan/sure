#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from finalize_result_bundle import finalize_bundle


class FinalizeResultBundleTests(unittest.TestCase):
    def test_verifies_canonical_container_identity_without_changing_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "result"
            model = Path(temporary) / "model"
            (model / "artifacts").mkdir(parents=True)
            (root / "predictions").mkdir(parents=True)
            image = "registry.example.com/demo@sha256:" + "a" * 64
            inventory = {
                "status": "ready",
                "model": {"name": "owner__demo"},
                "policy": {"eval_runtime": "container_only"},
                "container_runtime": {"target_image_ref": image},
            }
            (model / "artifacts/runtime_inventory.json").write_text(json.dumps(inventory))
            status = {"model_name": "owner__demo", "model_dir": str(model), "runtime": {"runtime_inventory": inventory}}
            status_path = root / "prediction_generation_status.json"
            status_path.write_text(json.dumps(status))
            (root / "protocol.yaml").write_text(yaml.safe_dump({"model": {"model_name": "owner__demo"}}))
            manifest_path = root / "predictions/manifest.json"
            manifest_path.write_text(json.dumps({"model_name": "owner__demo"}))
            prediction = root / "predictions/demo.jsonl"
            original = '{"key":"sample","speech_segments":[]}\n'
            prediction.write_text(original)

            finalize_bundle(root, root, model)

            self.assertEqual(json.loads(status_path.read_text())["model_name"], "owner__demo")
            self.assertEqual(json.loads(manifest_path.read_text())["model_name"], "owner__demo")
            self.assertEqual(prediction.read_text(), original)
            status["model_name"] = "different-model"
            status_path.write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "prediction model identity disagrees"):
                finalize_bundle(root, root, model)
            status["model_name"] = "owner__demo"
            status["runtime"]["runtime_inventory"]["container_runtime"]["target_image_ref"] = "registry.example.com/wrong@sha256:" + "b" * 64
            status_path.write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "prediction runtime identity disagrees"):
                finalize_bundle(root, root, model)

    def test_rejects_mount_alias_in_status_or_prediction_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "result"
            model = Path(temporary) / "model"
            (model / "artifacts").mkdir(parents=True)
            (root / "predictions").mkdir(parents=True)
            image = "registry.example.com/demo@sha256:" + "a" * 64
            inventory = {
                "status": "ready",
                "model": {"name": "owner__demo"},
                "policy": {"eval_runtime": "container_only"},
                "container_runtime": {"target_image_ref": image},
            }
            (model / "artifacts/runtime_inventory.json").write_text(json.dumps(inventory))
            status = {"model_name": "model", "runtime": {"runtime_inventory": inventory}}
            (root / "prediction_generation_status.json").write_text(json.dumps(status))
            (root / "protocol.yaml").write_text(yaml.safe_dump({"model": {"model_name": "owner__demo"}}))
            manifest = root / "predictions/manifest.json"
            manifest.write_text(json.dumps({"model_name": "owner__demo"}))

            with self.assertRaisesRegex(ValueError, "prediction model identity disagrees"):
                finalize_bundle(root, root, model)

            status["model_name"] = "owner__demo"
            (root / "prediction_generation_status.json").write_text(json.dumps(status))
            manifest.write_text(json.dumps({"model_name": "model"}))
            with self.assertRaisesRegex(ValueError, "prediction manifest identity disagrees"):
                finalize_bundle(root, root, model)

    def test_verifies_python_runtime_fields_that_are_declared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "result"
            model = Path(temporary) / "model"
            (model / "artifacts").mkdir(parents=True)
            (root / "predictions").mkdir(parents=True)
            runtime = {"runtime_id": "runtime-v1", "lock_sha256": "a" * 64}
            inventory = {
                "status": "ready",
                "model": {"name": "owner__demo"},
                "policy": {"eval_runtime": "python"},
                "model_runtime": runtime,
            }
            (model / "artifacts/runtime_inventory.json").write_text(json.dumps(inventory))
            status = {"model_name": "owner__demo", "runtime": {"runtime_inventory": inventory}}
            status_path = root / "prediction_generation_status.json"
            status_path.write_text(json.dumps(status))
            (root / "protocol.yaml").write_text(yaml.safe_dump({"model": {"model_name": "owner__demo"}}))
            (root / "predictions/manifest.json").write_text(json.dumps({"model_name": "owner__demo"}))

            finalize_bundle(root, root, model)

            status["runtime"]["runtime_inventory"]["model_runtime"]["lock_sha256"] = "b" * 64
            status_path.write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "prediction runtime identity disagrees"):
                finalize_bundle(root, root, model)

    def test_localizes_metadata_without_mutating_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "container-output"
            published = Path(temporary) / "published" / "run"
            predictions = root / "predictions"
            predictions.mkdir(parents=True)
            source = str(root.resolve())
            (root / "evaluation_payload.json").write_text(
                json.dumps({"artifact": f"{source}/metrics/report.json"}), encoding="utf-8"
            )
            (root / "protocol.yaml").write_text(
                yaml.safe_dump({"run": {"run_dir": source}}), encoding="utf-8"
            )
            prediction = json.dumps({"key": "demo", "normalized_prediction": f"literal {source}"}) + "\n"
            (predictions / "demo.jsonl").write_text(prediction, encoding="utf-8")
            (predictions / "manifest.json").write_text(
                json.dumps({"path": f"{source}/predictions/demo.jsonl"}), encoding="utf-8"
            )

            changed = finalize_bundle(root, published)

            self.assertIn("evaluation_payload.json", changed)
            self.assertEqual(
                json.loads((root / "evaluation_payload.json").read_text())["artifact"],
                str(published / "metrics" / "report.json"),
            )
            self.assertEqual((predictions / "demo.jsonl").read_text(), prediction)
            evidence = json.loads((root / "artifact_path_localization.json").read_text())
            self.assertFalse(evidence["prediction_content_modified"])


if __name__ == "__main__":
    unittest.main()
