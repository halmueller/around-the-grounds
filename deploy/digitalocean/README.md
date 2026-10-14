# Deploying the Freshies sites on a DigitalOcean droplet (Apache)

The droplet scrapes the tap lists itself, hourly from cron, and publishes each
site straight into its own Apache document root with `--output-dir`. No git
host, GitHub App, Temporal worker, or API key is involved (haiku and vision
are off for these sites).

One checkout and one user serve every Freshies site (seattlefreshies.com
first; see `FRESHIES-EXPANSION-PLAN.md` for the others). The commands below
use two shell variables, so they work for any of them. Set them in each shell
you paste into:

```bash
SITE=seattle-freshies          # the key of config/sites/<key>.json
DOMAIN=seattlefreshies.com     # the host of that site's public_url
```

For a second site on a droplet that already runs one, skip step 1 and do
steps 2 through 6 with the new values.

- Each published file is swapped in atomically, so visitors never see a
  half-written `data.json`.
- If **every** venue fails (e.g. the droplet loses its network), nothing is
  written and the last good copy stays up. Partial failures still publish, and
  the page names the venues it couldn't check.
- Files the site doesn't produce (a Search Console verification file, certbot's `.well-known/`) are
  left alone.

Commands below use `freshies` as the sites' user and the fork's
`feature/fresh-hop-site` branch; adjust as needed.

## 1. Sites' user, uv, and the code (once per droplet)

```bash
sudo adduser --disabled-password --gecos "" freshies
sudo -iu freshies

curl -LsSf https://astral.sh/uv/install.sh | sh     # installs to ~/.local/bin
exec bash -l                                          # pick up the new PATH

git clone -b feature/fresh-hop-site https://github.com/halmueller/around-the-grounds.git
cd around-the-grounds
uv sync --python 3.12 --no-dev      # uv fetches Python 3.12 if the OS lacks it
```

## 2. Dry run: can the droplet reach every tap list?

Datacenter IPs are more likely than home connections to get bot challenges
(this is what broke Saleh's Corner on the Ballard site). Check before going
live:

```bash
uv run --no-sync around-the-grounds --site "$SITE" --preview; echo "exit $?"
python3 - <<'EOF'
import json
d = json.load(open("public/data.json"))
listings = [e for e in d["events"] if e.get("kind") == "listing"]
print(len(listings), "fresh-hop beers at", len({e["venue_key"] for e in listings}), "places")
print(len(d["events"]) - len(listings), "events")
print("errors:", d["errors"] or "none")
EOF
grep -i "cloudflare\|403\|429" -m 20 <(uv run --no-sync around-the-grounds --site "$SITE" --verbose 2>&1) || echo "no blocks logged"
```

Compare with a run on your Mac. Any venue named in `errors` is unreachable
from the droplet.

## 3. Document root and first publish

```bash
sudo mkdir -p /var/www/$DOMAIN
sudo chown freshies:freshies /var/www/$DOMAIN
sudo -iu freshies ~/around-the-grounds/deploy/digitalocean/run.sh "$SITE"
ls -l /var/www/$DOMAIN     # index.html, data.json, events.ics
```

`run.sh` requires the site key (`seattle-freshies`, `portland-freshies`, or
`yakima-freshies`; a new site is added to `SITES` at the top of the script)
and publishes into `/var/www/<host of the site's public_url>`; set `WEB_ROOT`
to publish somewhere else.

## 4. Apache

```bash
sed "s/SITEDOMAIN/$DOMAIN/g" ~freshies/around-the-grounds/deploy/digitalocean/freshies-site.conf \
    | sudo tee /etc/apache2/sites-available/$DOMAIN.conf > /dev/null
sudo a2enmod headers
sudo a2ensite $DOMAIN
sudo apachectl configtest && sudo systemctl reload apache2
curl -s -H "Host: $DOMAIN" http://localhost/data.json | head -c 300; echo
```

`freshies-site.conf` is one virtual host for every site, with `SITEDOMAIN`
standing for the domain.

## 5. DNS and HTTPS

At the registrar, point the domain and `www` at the droplet (A records; AAAA
too if the droplet has IPv6). Once `dig +short $DOMAIN` returns the droplet's
address:

```bash
sudo certbot --apache -d $DOMAIN -d www.$DOMAIN
```

Choose the HTTP→HTTPS redirect. Certbot renews on its own timer.

## 6. Hourly refresh

```bash
sudo -iu freshies
mkdir -p ~/logs
crontab -e          # add the site's line from deploy/digitalocean/crontab.example
exit
sed 's/SITEUSER/freshies/g' ~freshies/around-the-grounds/deploy/digitalocean/logrotate.conf \
    | sudo tee /etc/logrotate.d/freshies
sudo rm -f /etc/logrotate.d/seattle-freshies    # the old single-site file, if present
```

Give each site its own minute, 15 minutes apart (Seattle runs at :07). Sites
also take turns: `run.sh` holds a lock shared by all of them while it scrapes,
because they share upstream hosts (Untappd, Google Sheets) and the scraper
only spaces out its own requests. A site whose turn has not come within 25
minutes skips that run (exit 75). The logrotate file covers every site's log
(`~freshies/logs/*.log`) and is installed once.

After the site's next run, check `~freshies/logs/$SITE.log`:

| Exit code | Meaning |
|-----------|---------|
| 0 | Clean run, site published |
| 2 | Some venues failed; site published, page names them |
| 1 | Nothing published (every venue failed, or a write error); last copy kept |
| 75 | Skipped: this site's previous run was still going, or another site's run did not finish in time |

Optional: create a check per site at healthchecks.io (hourly, with a grace
period) and put `HEALTHCHECK_URL=<its ping URL>` at the start of that site's
cron line (see `crontab.example`) to be emailed if runs stop or fail. A
`HEALTHCHECK_URL=` line of its own applies to every site in the crontab, so
use that form only while there is one site.
Exit codes 2 and 75 ping as success, so one unreachable venue does not alert;
only a run that published nothing does.

## Changes to the Apache config

Certbot copied the `:80` host into
`/etc/apache2/sites-available/$DOMAIN-le-ssl.conf` when it set up HTTPS, and
added the redirect to the `:80` file. Later changes to `freshies-site.conf` in
the repo reach neither file on their own. Copy the changed lines into **both**
files by hand, for each site (keep certbot's redirect and SSL lines), then:

```bash
sudo apachectl configtest && sudo systemctl reload apache2
curl -sI https://$DOMAIN/ | grep -i "strict-transport\|referrer\|location"
```

## Changing the home page with the season

`/` is a temporary (302) redirect to the list that is in season, so each
seasonal list keeps its own URL, and its search ranking, all year. To switch,
change the page name in the `RedirectMatch` line of **both** Apache files on
the droplet for each site (and in the repo's `freshies-site.conf`), and in
`public_templates/fresh-hop/index.html`, which is the same redirect for local
previews. Keep it a 302, leave the out-of-season pages and their tabs in
place, and never put a year in a page name.

```bash
sudo apachectl configtest && sudo systemctl reload apache2
curl -sI https://$DOMAIN/ | grep -i "^HTTP\|^location"   # 302, new page
```

## Analytics (optional)

The pages load `analytics.js`, which turns on TelemetryDeck only when
`analytics-config.js` in the web root supplies its app ID.
That file is not in the repo and the build never writes it, so keep it on the
droplet only. Each site gets its own file and its own TelemetryDeck app:

```bash
sudo -u freshies cp ~freshies/around-the-grounds/deploy/digitalocean/analytics-config.example.js \
    /var/www/$DOMAIN/analytics-config.js
sudo -u freshies nano /var/www/$DOMAIN/analytics-config.js    # fill in the app ID
```

Changes take effect without a publish. Browsers may keep the old copy for up
to an hour (the `.js` cache header). Until the file exists, the pages request
it, get a 404, and load no analytics.

## Updating

```bash
sudo -iu freshies
cd ~/around-the-grounds && git pull && uv sync --no-dev
```

`run.sh` never changes the environment itself (`uv run --no-sync`), so run
`uv sync` after every pull.

## Off-season

The seasonal lists overlap from August through February, so the hourly lines
can stay. In a quiet stretch, change a site's cron line to daily (e.g.
`7 9 * * *`) or comment it out. Each list already says when it is out of
season.
