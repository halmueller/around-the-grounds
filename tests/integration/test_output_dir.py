"""Tests for --output-dir: publishing a site straight into a web root."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List
from unittest.mock import AsyncMock, patch

import pytest

from around_the_grounds.main import main, publish_to_directory
from around_the_grounds.models import Event, SiteConfig, Venue
from around_the_grounds.scrapers.coordinator import ScrapingError

VENUES = [Venue(f"v{i}-taps", f"Venue {i}", f"https://v{i}.example") for i in range(2)]


def _site() -> SiteConfig:
    return SiteConfig(
        key="seattle-fall-beers",
        name="Seattle Fall Beers",
        template="fresh-hop",
        timezone="America/Los_Angeles",
        venues=VENUES,
    )


def _events() -> List[Event]:
    return [
        Event(
            "v0-taps",
            "Venue 0",
            "Fresh Hop IPA",
            datetime.now() + timedelta(hours=1),
            kind="listing",
        )
    ]


def _error(venue: Venue) -> ScrapingError:
    return ScrapingError(venue, "Network Error", "boom")


def _publish(events: List[Event], errors: List[ScrapingError], root: Path) -> bool:
    return asyncio.run(publish_to_directory(events, errors, _site(), root))


@pytest.fixture
def web_root(tmp_path: Path) -> Path:
    root = tmp_path / "seattlefallbeers.com"
    root.mkdir()
    (root / "robots.txt").write_text("User-agent: *\n")
    (root / ".well-known" / "acme-challenge").mkdir(parents=True)
    (root / ".well-known" / "acme-challenge" / "token").write_text("abc")
    (root / "data.json").write_text('{"old": true}')
    return root


def test_publishes_site_files(web_root: Path) -> None:
    assert _publish(_events(), [], web_root) is True

    data = json.loads((web_root / "data.json").read_text())
    assert data["total_events"] == 1
    assert data["events"][0]["title"] == "Fresh Hop IPA"
    assert (web_root / "index.html").read_text().startswith("<!DOCTYPE html>")
    assert (web_root / "events.ics").exists()


def test_leaves_unrelated_files_and_no_staging(web_root: Path) -> None:
    _publish(_events(), [], web_root)

    assert (web_root / "robots.txt").read_text() == "User-agent: *\n"
    assert (web_root / ".well-known" / "acme-challenge" / "token").read_text() == "abc"
    assert not list(web_root.glob(".atg-staging-*"))


def test_keeps_last_good_copy_when_every_venue_fails(web_root: Path) -> None:
    assert _publish([], [_error(v) for v in VENUES], web_root) is False
    assert (web_root / "data.json").read_text() == '{"old": true}'
    assert not (web_root / "index.html").exists()


def test_partial_failure_still_publishes(web_root: Path) -> None:
    assert _publish(_events(), [_error(VENUES[1])], web_root) is True
    data = json.loads((web_root / "data.json").read_text())
    assert data["errors"] == ["Failed to fetch information for: Venue 1"]


def test_empty_result_replaces_stale_data(web_root: Path) -> None:
    """Off-season: no fresh hops anywhere is a real result, not a failure."""
    assert _publish([], [], web_root) is True
    data = json.loads((web_root / "data.json").read_text())
    assert data["events"] == []


def test_missing_directory_fails(tmp_path: Path) -> None:
    assert _publish(_events(), [], tmp_path / "nope") is False


class TestCli:
    def _run(self, argv: List[str], **patches: Any) -> int:
        with patch(
            "around_the_grounds.main.load_site_config", return_value=_site()
        ), patch(
            "around_the_grounds.main.load_all_sites", return_value=[_site(), _site()]
        ), patch(
            "around_the_grounds.main.scrape_site",
            new_callable=AsyncMock,
            return_value=patches.get("scrape", (_events(), [])),
        ) as mock_scrape, patch(
            "around_the_grounds.main.publish_to_directory",
            new_callable=AsyncMock,
            return_value=patches.get("published", True),
        ) as mock_publish:
            code = main(argv)
        self.scrape_calls = mock_scrape.await_count
        self.publish_calls = mock_publish.await_args_list
        return code

    def test_publishes_the_selected_site(self, tmp_path: Path) -> None:
        argv = ["--site", "seattle-fall-beers", "--output-dir", str(tmp_path)]
        assert self._run(argv) == 0
        assert len(self.publish_calls) == 1
        assert self.publish_calls[0].args[3] == tmp_path

    def test_failed_publish_is_exit_1(self, tmp_path: Path) -> None:
        argv = ["--site", "seattle-fall-beers", "--output-dir", str(tmp_path)]
        assert self._run(argv, published=False) == 1

    def test_rejects_multiple_sites(self, tmp_path: Path, capsys: Any) -> None:
        assert self._run(["--site", "all", "--output-dir", str(tmp_path)]) == 1
        assert self.scrape_calls == 0
        assert "one site" in capsys.readouterr().out
