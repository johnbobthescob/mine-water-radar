from __future__ import annotations

import pytest

from radar.cli import main


def run_help(args: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_main_help_is_available_without_database_or_network(capsys):
    output = run_help(["--help"], capsys)
    for command in ("fetch", "score", "report", "all"):
        assert command in output


@pytest.mark.parametrize("command", ["fetch", "score", "report", "all"])
def test_subcommand_help_exposes_planned_options(command, capsys):
    output = run_help([command, "--help"], capsys)
    assert "--db" in output
    assert "--as-of" in output
    if command in {"fetch", "all"}:
        assert "--raw-dir" in output
        assert "--fixture-dir" in output
        assert "--tenement-site-limit" in output
    if command in {"fetch", "score", "all"}:
        assert "--reviewed-evidence" in output
    if command in {"report", "all"}:
        assert "--out" in output
        assert "--days" in output


@pytest.mark.parametrize("command", ["fetch", "score", "report", "all"])
def test_unfinished_subcommands_fail_clearly(command, capsys, tmp_path):
    result = main([command, "--db", str(tmp_path / "never-created.sqlite")])
    captured = capsys.readouterr()
    assert result == 1
    assert "not implemented in M1" in captured.err
    assert not (tmp_path / "never-created.sqlite").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["fetch", "--as-of", "20261122"],
        ["report", "--days", "0"],
        ["fetch", "--tenement-site-limit", "-1"],
    ],
)
def test_invalid_contract_inputs_are_rejected(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err

