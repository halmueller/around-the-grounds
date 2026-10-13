from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .brewery import Venue


@dataclass
class SiteConfig:
    key: str
    name: str
    template: str
    timezone: str
    venues: List[Venue]
    target_repo: str = ""
    generate_description: bool = True
    # Subdirectory within the target repo where template + data.json are written.
    # Empty string (default) writes to the repo root — used by sites served from
    # GitHub Pages at the repo root. Non-empty (e.g. "public") writes to that
    # subdirectory — used when the target repo is consumed by a host like Vercel
    # whose build output is scoped to a subfolder. The value also selects the
    # deploy strategy: empty → init + force-push, non-empty → clone + scoped add.
    deploy_subdir: str = ""
    # Public homepage for calendar attribution; never infer from the git remote.
    public_url: str = ""
    # Longer calendar entries become all-day with uncertain hours, never truncated.
    calendar_max_timed_hours: Optional[float] = None
    # Values for {{name}} placeholders in a template shared between sites
    # (e.g. {"place": "Seattle"}). Setting it turns substitution on for the
    # site; {{site_name}} and {{public_url}} are filled from the fields above.
    template_vars: Dict[str, str] = field(default_factory=dict)
