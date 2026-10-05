"""Tests for unified diff patch application."""

from __future__ import annotations

from learning_agent.core import agent_autonomy_runner, autonomy_patch
from learning_agent.core.workspace import read_file, resolve_path, write_file


def test_apply_unified_patch_replaces_single_line():
    original = "alpha\nbeta\ngamma\n"
    diff = """--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+new beta
 gamma
"""
    merged, warnings = autonomy_patch.apply_unified_patch(original, diff)
    assert "new beta" in merged
    assert merged.count("beta") == 0 or "new beta" in merged
    assert "alpha" in merged and "gamma" in merged


def test_parse_patch_blocks_reads_path_header():
    text = """```patch remote_app/foo.py
--- a/remote_app/foo.py
+++ b/remote_app/foo.py
@@ -1,1 +1,1 @@
-x
+y
```"""
    blocks = autonomy_patch.parse_patch_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].path == "remote_app/foo.py"


def test_apply_patch_blocks_updates_existing_file():
    rel = "tests/_scratch_patch/target.py"
    try:
        write_file(rel, "one\ntwo\nthree\n")
        reply = """```patch tests/_scratch_patch/target.py
--- a/tests/_scratch_patch/target.py
+++ b/tests/_scratch_patch/target.py
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
```"""
        result = agent_autonomy_runner.apply_patch_blocks(reply)
        assert result["blockCount"] == 1
        assert result["failedCount"] == 0
        assert result["changedPaths"][0].endswith("target.py")
        assert read_file(rel)["content"] == "one\nTWO\nthree\n"
    finally:
        path = resolve_path(rel)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_apply_autonomy_blocks_applies_patch_then_write():
    patch_rel = "tests/_scratch_patch/combo_patch.py"
    write_rel = "tests/_scratch_patch/combo_new.txt"
    try:
        write_file(patch_rel, "keep\nold\n")
        reply = (
            "```patch tests/_scratch_patch/combo_patch.py\n"
            "--- a/tests/_scratch_patch/combo_patch.py\n"
            "+++ b/tests/_scratch_patch/combo_patch.py\n"
            "@@ -1,2 +1,2 @@\n"
            " keep\n"
            "-old\n"
            "+NEW\n"
            "```\n"
            "```write tests/_scratch_patch/combo_new.txt\n"
            "hello\n"
            "```"
        )
        result = agent_autonomy_runner.apply_autonomy_blocks(reply)
        assert result["patchBlockCount"] == 1
        assert result["writeBlockCount"] == 1
        assert read_file(patch_rel)["content"] == "keep\nNEW\n"
        assert read_file(write_rel)["content"].strip() == "hello"
    finally:
        for rel in (patch_rel, write_rel):
            path = resolve_path(rel)
            path.unlink(missing_ok=True)
        parent = resolve_path("tests/_scratch_patch")
        if parent.exists():
            parent.rmdir()
