"""deploy/digitalocean/run.sh: which site it refreshes, and into which web root.

Runs the real script with stub ``flock`` and ``uv`` commands on PATH, so no
scrape happens and the test works on machines without flock (macOS).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from around_the_grounds.config.loader import load_all_sites

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "digitalocean"
SCRIPT = DEPLOY / "run.sh"

# Like flock(1): skip the options and the lock file, then run the command.
FLOCK_STUB = """#!/usr/bin/env bash
echo "flock $*" >> "$CALLS"
while [[ "$1" == -* ]]; do
    case "$1" in
        -E|-w) shift 2 ;;
        *) shift ;;
    esac
done
shift
exec "$@"
"""
UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$CALLS"
exit "${UV_EXIT:-0}"
"""

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="needs bash and python3",
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A checkout holding just the site configs run.sh reads."""
    sites = tmp_path / "repo" / "around_the_grounds" / "config" / "sites"
    sites.mkdir(parents=True)
    (sites / "seattle-freshies.json").write_text(
        json.dumps({"public_url": "https://seattlefreshies.com"})
    )
    (sites / "hop-town-freshies.json").write_text(
        json.dumps({"public_url": "https://www.hoptown.example:8443/path/"})
    )
    (sites / "no-url.json").write_text(json.dumps({"key": "no-url"}))
    return tmp_path / "repo"


def _run(
    tmp_path: Path, fake_repo: Path, args: List[str], env: Optional[Dict[str, str]]
) -> "subprocess.CompletedProcess[str]":
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("flock", FLOCK_STUB), ("uv", UV_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        # run.sh puts $HOME/.local/bin first on PATH; keep a real uv out of it.
        "HOME": str(tmp_path / "home"),
        "REPO_DIR": str(fake_repo),
        "CALLS": str(tmp_path / "calls.txt"),
    }
    full_env.update(env or {})
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def _calls(tmp_path: Path) -> List[str]:
    path = tmp_path / "calls.txt"
    return path.read_text().splitlines() if path.exists() else []


def test_default_is_seattle_with_its_existing_paths(
    tmp_path: Path, fake_repo: Path
) -> None:
    """The cron line installed before run.sh took a site key keeps working."""
    result = _run(tmp_path, fake_repo, [], None)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp_path)
    assert calls[-1] == (
        "uv run --no-sync around-the-grounds --site seattle-freshies "
        "--output-dir /var/www/seattlefreshies.com"
    )
    assert calls[0].startswith("flock -n -E 75 /tmp/seattle-freshies.lock ")


def test_site_key_argument_picks_the_site_and_its_web_root(
    tmp_path: Path, fake_repo: Path
) -> None:
    result = _run(tmp_path, fake_repo, ["hop-town-freshies"], None)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp_path)
    assert calls[-1] == (
        "uv run --no-sync around-the-grounds --site hop-town-freshies "
        "--output-dir /var/www/www.hoptown.example"
    )
    assert calls[0].startswith("flock -n -E 75 /tmp/hop-town-freshies.lock ")
    assert "hop-town-freshies: starting refresh" in result.stdout


def test_sites_queue_on_one_shared_lock(tmp_path: Path, fake_repo: Path) -> None:
    """Sites share upstream hosts, so only one scrapes at a time."""
    _run(tmp_path, fake_repo, [], None)
    _run(tmp_path, fake_repo, ["hop-town-freshies"], None)

    queue = [c for c in _calls(tmp_path) if c.startswith("flock -w ")]
    assert len(queue) == 2
    assert {c.split()[5] for c in queue} == {"/tmp/freshies-queue.lock"}


def test_environment_overrides(tmp_path: Path, fake_repo: Path) -> None:
    env = {
        "SITE_KEY": "hop-town-freshies",
        "WEB_ROOT": "/srv/hops",
        "LOCK_FILE": "/tmp/mine.lock",
    }
    result = _run(tmp_path, fake_repo, [], env)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp_path)
    assert calls[-1].endswith("--site hop-town-freshies --output-dir /srv/hops")
    assert calls[0].startswith("flock -n -E 75 /tmp/mine.lock ")


@pytest.mark.parametrize("key", ["no-url", "not-a-site"])
def test_site_without_a_public_url_fails_before_scraping(
    tmp_path: Path, fake_repo: Path, key: str
) -> None:
    result = _run(tmp_path, fake_repo, [key], None)

    assert result.returncode == 1
    assert "set WEB_ROOT" in result.stdout
    assert _calls(tmp_path) == []


@pytest.mark.parametrize("key", ["../../etc/passwd", "two words", "a;b"])
def test_rejects_keys_that_are_not_a_slug(
    tmp_path: Path, fake_repo: Path, key: str
) -> None:
    result = _run(tmp_path, fake_repo, [key], None)

    assert result.returncode == 1
    assert "not a site key" in result.stdout
    assert _calls(tmp_path) == []


def test_scrape_exit_code_is_passed_through(tmp_path: Path, fake_repo: Path) -> None:
    result = _run(tmp_path, fake_repo, [], {"UV_EXIT": "2"})

    assert result.returncode == 2
    assert "finished with exit code 2" in result.stdout


def test_real_site_configs_give_run_sh_a_web_root(tmp_path: Path) -> None:
    """Every fresh-hop site resolves to /var/www/<its domain> from the real repo."""
    for site in load_all_sites():
        if site.template != "fresh-hop":
            continue
        (tmp_path / "calls.txt").unlink(missing_ok=True)
        result = _run(tmp_path, REPO, [site.key], None)
        assert result.returncode == 0, result.stdout + result.stderr
        host = site.public_url.split("://", 1)[1].split("/", 1)[0]
        assert _calls(tmp_path)[-1].endswith(f"--output-dir /var/www/{host}")


def test_apache_conf_is_one_template_for_every_site() -> None:
    conf = (DEPLOY / "freshies-site.conf").read_text()
    body = conf[conf.index("<VirtualHost") :]
    assert "ServerName SITEDOMAIN\n" in body
    assert "DocumentRoot /var/www/SITEDOMAIN\n" in body
    assert "seattlefreshies" not in body


def test_crontab_example_names_the_site_on_each_line() -> None:
    lines = [
        line.lstrip("# ")
        for line in (DEPLOY / "crontab.example").read_text().splitlines()
        if "run.sh" in line and "* * * *" in line
    ]
    assert lines
    keys = {site.key for site in load_all_sites()}
    minutes = {}
    for line in lines:
        key = line.split("run.sh ", 1)[1].split()[0]
        assert f">> $HOME/logs/{key}.log" in line
        minutes.setdefault(key, line.split()[0])
        if not line.startswith(minutes[key]):
            pytest.fail(f"{key} has two different minutes")
    assert "seattle-freshies" in minutes and minutes["seattle-freshies"] == "7"
    # Live sites run at different minutes; lines for sites not configured yet
    # are examples and stay commented out.
    live = [m for k, m in minutes.items() if k in keys]
    assert len(live) == len(set(live))
