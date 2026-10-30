"""A reused DXF filename must never select another file's CFD result."""

import json
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import riverflow_cfd_uploaded


class UploadedCFDTests(unittest.TestCase):
    def test_published_diagnostic_replaces_unstable_runs(self):
        digest = "47154b381560b10b58d2729f9e2ae79dc90ff1f24af8a7640d36a41b15f68060"
        match = riverflow_cfd_uploaded.load_matching_run(digest)
        self.assertIsNotNone(match)
        folder, manifest, cases = match
        self.assertFalse(manifest["quality_gate"]["mesh_convergence"])
        self.assertFalse(manifest["quality_gate"]["physical_validation"])
        self.assertEqual(set(cases), {"reference20", "automatic"})
        self.assertAlmostEqual(cases["reference20"][1]["time_profile"][-1][
            "fraction_cell_reverse_below_minus_0_02"], .1801195815, places=6)
        self.assertAlmostEqual(cases["automatic"][1]["time_profile"][-1][
            "fraction_cell_reverse_below_minus_0_02"], .4215246637, places=6)
        for key in cases:
            with gzip.open(folder / key / "flow_2d.html.gz", "rt", encoding="utf-8") as source:
                html = source.read()
            self.assertIn('"cmin":-0.6', html)
            self.assertIn('"cmax":0.6', html)

    def test_uploaded_map_reveals_slow_flow_without_changing_saved_values(self):
        digest = "47154b381560b10b58d2729f9e2ae79dc90ff1f24af8a7640d36a41b15f68060"
        folder, _, _ = riverflow_cfd_uploaded.load_matching_run(digest)
        with gzip.open(folder / "reference20" / "flow_2d.html.gz", "rt",
                       encoding="utf-8") as source:
            saved = source.read()
        detail = riverflow_cfd_uploaded._browser_compatible_2d(saved)
        comparison = riverflow_cfd_uploaded._browser_compatible_2d(
            saved, detail_scale=False)
        self.assertIn('"cmax":0.15,"cmin":-0.15', detail)
        self.assertIn('"cmax":0.6,"cmin":-0.6', comparison)
        self.assertIn('if (cursor >= sequence.length)', detail)
        self.assertNotIn('cursor = (cursor + 1) % sequence.length;', detail)
        self.assertNotIn('setTimeout(advance, 500)', detail)
        self.assertIn('"opacity":0.55,"size":3', detail)
        self.assertIn('"redraw":false', detail)

    def test_cfd_bundle_is_selected_by_full_content_hash(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "tmp") as temp:
            folder = Path(temp) / digest[:12]
            scenario = folder / "reference20"
            scenario.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "schema": 2,
                "status": "diagnostic_only_not_purchase_or_lap",
                "source_dxf_sha256": digest,
                "scenarios": {"reference20": "20 bombas"}}))
            (scenario / "metadata.json").write_text(json.dumps({
                "source_dxf_sha256": digest}))
            (scenario / "transient_report.json").write_text(json.dumps({
                "source_dxf_sha256": digest,
                "max_courant_observed": .15}))
            (scenario / "flow_2d.html.gz").write_bytes(b"placeholder")
            (scenario / "flow_3d.html.gz").write_bytes(b"placeholder")
            with patch.object(riverflow_cfd_uploaded, "ASSETS", Path(temp)):
                self.assertIsNotNone(riverflow_cfd_uploaded.load_matching_run(digest))
                self.assertIsNone(riverflow_cfd_uploaded.load_matching_run("b" * 64))
                (folder / "manifest.json").write_text(json.dumps({
                    "source_dxf_sha256": "b" * 64,
                    "source_dxf_name": "same.dxf"}))
                self.assertIsNone(riverflow_cfd_uploaded.load_matching_run(digest))


if __name__ == "__main__":
    unittest.main()
