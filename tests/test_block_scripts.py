"""check_one_file.py and loading_files.py. These tests need no database.

Bugs:
- check_one_file.py's block fixer called checkLine(file_name, 1), which takes
  three arguments, so a block that failed the schema crashed with a TypeError
  (exit 1) instead of having line 5 removed and exiting 8. The shell only stops
  on exit 8, so it went on to load the invalid block.
- loading_files.py used sys in its error handler without importing it, so a
  bad block raised NameError instead of reporting which block failed.
"""
import json
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import BLOCK_FILE, BLOCK_HEIGHT

# Connection details that fail immediately: these tests must not need a database
NO_DB = {"db_name": "none", "db_user": "none", "db_password": "", "db_host": "127.0.0.1", "db_port": "1"}


class BlockScriptTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "work").mkdir()
        (root / "blocks").mkdir()
        self.workdir = helpers.make_workdir(root / "work", NO_DB)
        self.blocks = root / "blocks"

    def write_block(self, lines):
        path = self.blocks / BLOCK_HEIGHT
        path.write_text("".join(lines))
        return path

    def run_check(self, path):
        return helpers.run_script_subprocess(
            "check_one_file.py", self.workdir, {"FILE_PATH": str(path), "FILE_NAME": path.name}
        )


class CheckOneFileTest(BlockScriptTest):
    def test_valid_block_passes_and_is_untouched(self):
        original = BLOCK_FILE.read_text()
        path = self.write_block([original])
        result = self.run_check(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), original)

    def test_schema_failure_removes_fifth_line_and_exits_8(self):
        lines = BLOCK_FILE.read_text().splitlines(keepends=True)
        self.assertEqual(lines[4].strip(), '"total": 1,')
        # Malformed 5th line: valid JSON, but 'total' must be an integer
        lines[4] = lines[4].replace('"total": 1,', '"total": "1",')
        path = self.write_block(lines)

        result = self.run_check(path)

        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(path.read_text(), "".join(lines[:4] + lines[5:]),
                         "only line 5 should be removed")
        self.assertIn('Deleted line 5 of 7027410: "total": "1",', result.stderr)

    def test_schema_failure_does_not_touch_files_in_working_directory(self):
        # The old fixer opened file_name relative to the working directory
        decoy = self.workdir / BLOCK_HEIGHT
        decoy.write_text("line1\nline2\nline3\nline4\nline5\nline6\n")
        lines = BLOCK_FILE.read_text().splitlines(keepends=True)
        lines[4] = '      "total": "1",\n'
        result = self.run_check(self.write_block(lines))
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(decoy.read_text(), "line1\nline2\nline3\nline4\nline5\nline6\n")


class LoadingFilesTest(BlockScriptTest):
    def test_bad_block_reports_block_instead_of_nameerror(self):
        block = json.loads(BLOCK_FILE.read_text())
        del block["block_id"]
        path = self.write_block([json.dumps(block)])

        result = helpers.run_script_subprocess(
            "loading_files.py", self.workdir, {"FILE_PATH": str(path), "FILE_NAME": path.name}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("NameError", result.stderr)
        self.assertIn("Error with loading block info in block 7027410", result.stderr)


if __name__ == "__main__":
    unittest.main()
