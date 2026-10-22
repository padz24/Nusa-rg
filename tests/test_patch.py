"""The ghost patch: parsing, refusing, staging, and applying."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg import memory, patch
from nusa_rg.cli import main

DIFF = """--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
+import sys
 
 def main():
     pass
"""


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ------------------------------------------------------------------ parsing
def test_a_diff_is_read_into_file_patches():
    patches = patch.parse_diff(DIFF)

    assert len(patches) == 1
    assert patches[0].path == "src/app.py"
    assert patches[0].added == 1
    assert patches[0].removed == 0


def test_a_path_that_leaves_the_project_is_refused():
    with pytest.raises(patch.PatchError):
        patch.parse_diff("--- a/../etc/passwd\n+++ b/../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n")


def test_an_absolute_path_is_refused():
    with pytest.raises(patch.PatchError):
        patch.parse_diff("--- a//etc/passwd\n+++ b//etc/passwd\n@@ -1 +1 @@\n-a\n+b\n")


def test_a_diff_without_a_file_is_refused():
    with pytest.raises(patch.PatchError):
        patch.parse_diff("just some text\n")


def test_the_diff_is_taken_out_of_a_model_answer():
    answer = "Here you go:\n```diff\n" + DIFF + "```\nThat should work."

    extracted = patch.extract_diff(answer)

    assert extracted.startswith("--- a/src/app.py")
    assert "```" not in extracted


# ------------------------------------------------------------------ applying
def test_a_patch_is_applied_to_a_file(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "app.py"
    target.write_text("import os\n\ndef main():\n    pass\n", encoding="utf-8")

    patch.apply_to_tree(patch.parse_diff(DIFF), tmp_path, tmp_path)

    assert "import sys" in target.read_text(encoding="utf-8")


def test_a_patch_that_no_longer_matches_is_refused(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "app.py"
    target.write_text("import os  # changed\n\ndef main():\n    pass\n",
                      encoding="utf-8")

    with pytest.raises(patch.PatchError):
        patch.apply_to_tree(patch.parse_diff(DIFF), tmp_path, tmp_path)


def test_a_patch_cannot_write_through_a_symbolic_link(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep\n", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "link").symlink_to(outside)

    diff = "--- a/link/secret.txt\n+++ b/link/secret.txt\n@@ -1 +1 @@\n-keep\n+changed\n"

    with pytest.raises(patch.PatchError):
        patch.apply_to_tree(patch.parse_diff(diff), root, root)
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep\n"


# ------------------------------------------------------------------- storing
def test_a_patch_is_staged_with_its_own_tree(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("import os\n\ndef main():\n    pass\n",
                                          encoding="utf-8")
    store = patch.PatchStore(base=tmp_path / "patches")
    key = memory.project_key(str(root))

    staged = store.create(key, "add the import", DIFF, patch.parse_diff(DIFF),
                          root=str(root))

    assert staged.files[0].path == "src/app.py"
    tree_file = store.tree(key, staged.id) / "src" / "app.py"
    assert "import sys" in tree_file.read_text(encoding="utf-8")
    # The real project is untouched.
    assert "import sys" not in (root / "src" / "app.py").read_text(encoding="utf-8")


def test_a_stored_patch_can_be_listed_and_thrown_away(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("import os\n\ndef main():\n    pass\n",
                                          encoding="utf-8")
    store = patch.PatchStore(base=tmp_path / "patches")
    key = memory.project_key(str(root))
    staged = store.create(key, "add the import", DIFF, patch.parse_diff(DIFF),
                          root=str(root))

    assert [item.id for item in store.list(key)] == [staged.id]
    assert store.discard(key, staged.id) is True
    assert store.list(key) == []


# ----------------------------------------------------------------------- CLI
def test_patch_review_shows_the_diff(runner, tmp_path, sample_project):
    (sample_project / "src" / "app.py").write_text(
        "import os\n\ndef main():\n    pass\n", encoding="utf-8")
    run(runner, ["index", str(sample_project)])
    store = patch.PatchStore()
    key = memory.project_key(str(sample_project))
    store.create(key, "add the import", DIFF, patch.parse_diff(DIFF),
                 root=str(sample_project))

    result = run(runner, ["patch", "review"])

    assert result.exit_code == 0
    assert "src/app.py" in result.output


def test_patch_test_without_a_command_says_it_did_not_run(runner, sample_project):
    (sample_project / "src" / "app.py").write_text(
        "import os\n\ndef main():\n    pass\n", encoding="utf-8")
    run(runner, ["index", str(sample_project)])
    store = patch.PatchStore()
    key = memory.project_key(str(sample_project))
    store.create(key, "add the import", DIFF, patch.parse_diff(DIFF),
                 root=str(sample_project))

    result = run(runner, ["patch", "test"])

    assert result.exit_code == 0
    assert "not run" in result.output


def test_fix_stages_the_patch_the_model_proposed(runner, sample_project,
                                                 monkeypatch):
    (sample_project / "src" / "app.py").write_text(
        "import os\n\ndef main():\n    pass\n", encoding="utf-8")
    run(runner, ["index", str(sample_project)])

    class Stub:
        name = "stub"

        def generate(self, prompt, **kwargs):
            return type("R", (), {"text": "```diff\n" + DIFF + "```",
                                  "usage": None})()

        def health_check(self):
            return True, "ok"

    monkeypatch.setattr("nusa_rg.cli.llm.build_client",
                        lambda config, **kwargs: Stub())

    result = run(runner, ["fix", "add the import"])

    assert result.exit_code == 0, result.output
    assert "staged" in result.output
    assert "src/app.py" in result.output
    assert patch.PatchStore().list(memory.project_key(str(sample_project)))


def test_patch_apply_writes_the_change(runner, sample_project):
    run(runner, ["index", str(sample_project)])
    target = sample_project / "src" / "app.py"
    target.write_text("import os\n\ndef main():\n    pass\n", encoding="utf-8")
    store = patch.PatchStore()
    key = memory.project_key(str(sample_project))
    store.create(key, "add the import", DIFF, patch.parse_diff(DIFF),
                 root=str(sample_project))

    result = run(runner, ["patch", "apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert "import sys" in target.read_text(encoding="utf-8")
