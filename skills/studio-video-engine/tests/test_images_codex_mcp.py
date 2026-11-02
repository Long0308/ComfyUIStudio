"""N79: image exec disables account MCP servers per call; no real Codex is launched."""

import pytest

from test_images_codex import Setup, no_auth_reads  # noqa: F401 (fixture re-used)


@pytest.mark.parametrize("mode", ["dry-run", "submit", "failover"])
def test_images_codex_exec_disables_mcp_servers(tmp_path, no_auth_reads, mode):
    setup = Setup(tmp_path)
    if mode == "failover":
        setup.flag("acct1", "quota.flag")
    result = setup.run(dry_run=mode == "dry-run")
    if mode == "dry-run":
        # The dry-run includes the binary prefix; fake CLI logs start at `exec`.
        planned = result["argv_without_prompt"]
        calls = [planned[planned.index("exec"):]]
        assert not setup.calls("acct1") and not setup.calls("acct2")
    else:
        calls = [call["argv"] for label in ("acct1", "acct2") for call in setup.calls(label)]
        assert len(calls) == (2 if mode == "failover" else 1)
    folder = setup.out / "S01_A" / "codex-exec" / result["take"]
    for argv in calls:
        assert ["-c", "mcp_servers={}"] == argv[1:3]
        # Keep every existing flag and attachment exactly as before.
        assert argv[3:11] == ["--skip-git-repo-check", "--json", "-s", "read-only",
                              "-C", str(folder / "work"), "-o", str(folder / "last-message.txt")]
        assert argv[11::2] == ["-i", "-i", "-i"]
