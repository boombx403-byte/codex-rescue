from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_rescue.alpha7.compatibility.engine import CompatibilityEngine
from codex_rescue.alpha7.compatibility.path_remap import PathRemappingEngine
from codex_rescue.alpha7.compatibility.portable import PortableSessionEngine
from codex_rescue.alpha7.graph import PathNamespace


class CompatibilityAndPortableTests(unittest.TestCase):
    def test_compatibility_engine(self):
        # Supported schemas
        c1 = CompatibilityEngine.evaluate(rollout_schema=1, sqlite_schema=1)
        self.assertTrue(c1.mutation_allowed)

        # Unknown rollout schema
        c2 = CompatibilityEngine.evaluate(rollout_schema=99, sqlite_schema=1)
        self.assertFalse(c2.mutation_allowed)
        self.assertEqual(c2.rejection_reason, "UNKNOWN_ROLLOUT_SCHEMA_99")

        # Unknown sqlite schema
        c3 = CompatibilityEngine.evaluate(rollout_schema=1, sqlite_schema=99)
        self.assertFalse(c3.mutation_allowed)
        self.assertEqual(c3.rejection_reason, "UNKNOWN_SQLITE_SCHEMA_99")

    def test_path_remapping_engine(self):
        # Windows to WSL
        r1 = PathRemappingEngine.translate_path(r"C:\Users\Project\src", target_platform="wsl")
        self.assertEqual(r1.target_path, "/mnt/c/Users/Project/src")
        self.assertEqual(r1.target_namespace, PathNamespace.WSL_MNT)

        # WSL to Windows
        r2 = PathRemappingEngine.translate_path("/mnt/d/code/rescue", target_platform="windows")
        self.assertEqual(r2.target_path, r"D:\code\rescue")
        self.assertEqual(r2.target_namespace, PathNamespace.WINDOWS_STANDARD)

        # Long path prefix stripping
        r3 = PathRemappingEngine.translate_path(r"\\?\C:\foo\bar", target_platform="windows")
        self.assertEqual(r3.target_path, r"C:\foo\bar")

    def test_portable_export_inspect_import_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_file = tmp / "session_export.jsonl"
            source_file.write_text('{"turn":1,"msg":"hello"}\n{"turn":2,"msg":"world"}\n', encoding="utf-8")

            pkg_zip = tmp / "export.rescue.zip"
            manifest = PortableSessionEngine.export_session(
                source_file, pkg_zip, workspace_path=r"C:\workspaces\project"
            )
            self.assertEqual(manifest.session_id, "session_export")
            self.assertEqual(manifest.records_count, 2)
            self.assertEqual(manifest.source_integrity, "PROVEN_COMPLETE")

            # Inspect
            inspected = PortableSessionEngine.inspect_package(pkg_zip)
            self.assertEqual(inspected.session_id, "session_export")
            self.assertEqual(inspected.rollout_sha256, manifest.rollout_sha256)

            # Plan import into target codex home
            target_home = tmp / "target_codex"
            plan = PortableSessionEngine.plan_import(pkg_zip, target_home)
            self.assertTrue(plan.is_safe)
            self.assertFalse(plan.has_conflict)

            # Dry run
            dry_res = PortableSessionEngine.execute_import(pkg_zip, target_home, plan, dry_run=True)
            self.assertTrue(dry_res["success"])
            self.assertEqual(dry_res["action"], "DRY_RUN_PASSED")

            # Real import
            real_res = PortableSessionEngine.execute_import(pkg_zip, target_home, plan, dry_run=False)
            self.assertTrue(real_res["success"])
            self.assertEqual(real_res["action"], "IMPORTED")

            imported_file = target_home / "sessions" / "session_export.jsonl"
            self.assertTrue(imported_file.exists())
            self.assertEqual(imported_file.read_text(encoding="utf-8"), source_file.read_text(encoding="utf-8"))

            # Conflict detection on second import
            conflict_plan = PortableSessionEngine.plan_import(pkg_zip, target_home)
            self.assertTrue(conflict_plan.has_conflict)
            self.assertFalse(conflict_plan.is_safe)
            conflict_res = PortableSessionEngine.execute_import(pkg_zip, target_home, conflict_plan)
            self.assertFalse(conflict_res["success"])


if __name__ == "__main__":
    unittest.main()
