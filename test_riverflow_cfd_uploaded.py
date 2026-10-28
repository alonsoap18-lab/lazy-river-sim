"""A reused DXF filename must never select another file's CFD result."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import riverflow_cfd_uploaded


class UploadedCFDTests(unittest.TestCase):
    def test_cfd_bundle_is_selected_by_full_content_hash(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "tmp") as temp:
            folder = Path(temp) / digest[:12]
            scenario = folder / "reference20"
            scenario.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "source_dxf_sha256": digest,
                "scenarios": {"reference20": "20 bombas"}}))
            (scenario / "metadata.json").write_text(json.dumps({
                "source_dxf_sha256": digest}))
            (scenario / "transient_report.json").write_text(json.dumps({
                "source_dxf_sha256": digest}))
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
