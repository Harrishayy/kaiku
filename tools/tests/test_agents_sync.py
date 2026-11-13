import shutil

from tools.agents_sync import ROOT, check


def test_repo_agent_files_and_module_index_in_sync():
    problems = check(ROOT, fix=False)
    assert not problems, "run `make agents` and fix:\n" + "\n".join(problems)


def test_checker_catches_drift(tmp_path):
    root = tmp_path / "repo"
    (root / "m").mkdir(parents=True)
    (root / "m" / "CLAUDE.md").write_text("@AGENTS.md\n")  # redundant pointer must be flagged
    (root / "m" / "README.md").write_text("# m\n")
    (root / "modules.toml").write_text(
        '[[module]]\nname="m"\npath="m"\nowner="A"\nkind="node"\nsummary="x"\nemits=["obs.nope"]\n'
    )
    shutil.copy(ROOT / "AGENTS.md", root / "AGENTS.md")
    problems = "\n".join(check(root, fix=False))
    for expected in ("AGENTS.md missing", "remove CLAUDE.md", "remove README.md", ".gemini/settings.json",
                     "obs.nope", "no module emits", "module index is stale"):
        assert expected in problems, expected


def test_missing_sections_are_reported(tmp_path):
    root = tmp_path / "repo"
    (root / "m").mkdir(parents=True)
    (root / "m" / "AGENTS.md").write_text("# m\n\n## Purpose\nx\n")
    (root / "modules.toml").write_text('[[module]]\nname="m"\npath="m"\nowner="A"\nkind="node"\nsummary="x"\n')
    shutil.copy(ROOT / "AGENTS.md", root / "AGENTS.md")
    assert "missing sections: Consumes" in "\n".join(check(root, fix=False))
