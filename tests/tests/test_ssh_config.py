from __future__ import annotations

from pathlib import Path

from learning_agent.core.ssh_config import find_config_host, parse_ssh_config, parse_ssh_target


def test_parse_ssh_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        """
Host frota remote_app-test
    HostName <REMOTE_HOST>
    User ubuntu
    IdentityFile ~/.ssh/frota.pem

Host *
    ForwardAgent yes
""",
        encoding="utf-8",
    )
    hosts = parse_ssh_config(cfg)
    names = {h.name for h in hosts}
    assert "frota" in names
    assert "remote_app-test" in names
    assert "*" not in names

    frota = find_config_host("frota", cfg)
    assert frota is not None
    assert frota.hostname == "<REMOTE_HOST>"
    assert frota.user == "ubuntu"


def test_parse_ssh_target_user_host() -> None:
    parsed = parse_ssh_target("ubuntu@203.0.113.10")
    assert parsed["user"] == "ubuntu"
    assert parsed["host"] == "203.0.113.10"


def test_parse_ssh_target_alias(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("Host myvm\n  HostName 10.0.0.5\n  User dev\n", encoding="utf-8")
    parsed = parse_ssh_target("myvm", cfg)
    assert parsed["ssh_config_alias"] == "myvm"
    assert parsed["host"] == "10.0.0.5"
    assert parsed["user"] == "dev"
