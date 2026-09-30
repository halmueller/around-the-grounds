# Deploying seattlefreshies.com on a DigitalOcean droplet (Apache)

The droplet scrapes the tap lists itself, hourly from cron, and publishes the
site straight into an Apache document root with `--output-dir`. No git host,
GitHub App, Temporal worker or API key is involved (haiku and vision are off
for this site).

- Each published file is swapped in atomically, so visitors never see a
  half-written `data.json`.
- If **every** venue fails (e.g. the droplet loses its network), nothing is
  written and the last good copy stays up. Partial failures still publish, and
  the page names the venues it couldn't check.
- Files the site doesn't produce (a Search Console verification file, certbot's `.well-known/`) are
  left alone.

Commands below use `freshies` as the site user and the fork's
`feature/fresh-hop-site` branch; adjust as needed.

## 1. Site user, uv and the code

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
uv run --no-sync around-the-grounds --site seattle-freshies --preview; echo "exit $?"
python3 - <<'EOF'
import json
d = json.load(open("public/data.json"))
listings = [e for e in d["events"] if e.get("kind") == "listing"]
print(len(listings), "fresh-hop beers at", len({e["venue_key"] for e in listings}), "places")
print(len(d["events"]) - len(listings), "events")
print("errors:", d["errors"] or "none")
EOF
grep -i "cloudflare\|403\|429" -m 20 <(uv run --no-sync around-the-grounds --site seattle-freshies --verbose 2>&1) || echo "no blocks logged"
```

Compare with a run on your Mac. Any venue named in `errors` is unreachable
from the droplet.

## 3. Document root and first publish

```bash
sudo mkdir -p /var/www/seattlefreshies.com
sudo chown freshies:freshies /var/www/seattlefreshies.com
sudo -iu freshies ~/around-the-grounds/deploy/digitalocean/run.sh
ls -l /var/www/seattlefreshies.com     # index.html, data.json, events.ics
```

## 4. Apache

```bash
sudo cp ~freshies/around-the-grounds/deploy/digitalocean/seattlefreshies.com.conf \
    /etc/apache2/sites-available/
sudo a2enmod headers
sudo a2ensite seattlefreshies.com
sudo apachectl configtest && sudo systemctl reload apache2
curl -s -H "Host: seattlefreshies.com" http://localhost/data.json | head -c 300; echo
```

## 5. DNS and HTTPS

At the registrar, point `seattlefreshies.com` and `www` at the droplet
(A records; AAAA too if the droplet has IPv6). Once `dig +short
seattlefreshies.com` returns the droplet's address:

```bash
sudo certbot --apache -d seattlefreshies.com -d www.seattlefreshies.com
```

Choose the HTTP→HTTPS redirect. Certbot renews on its own timer.

## 6. Hourly refresh

```bash
sudo -iu freshies
mkdir -p ~/logs
crontab -e          # paste the line from deploy/digitalocean/crontab.example
exit
sed 's/SITEUSER/freshies/g' ~freshies/around-the-grounds/deploy/digitalocean/logrotate.conf \
    | sudo tee /etc/logrotate.d/seattle-freshies
```

After the next :07, check `~freshies/logs/seattle-freshies.log`:

| Exit code | Meaning |
|-----------|---------|
| 0 | Clean run, site published |
| 2 | Some venues failed; site published, page names them |
| 1 | Nothing published (every venue failed, or a write error); last copy kept |
| 75 | Skipped: the previous run was still going |

Optional: create a check at healthchecks.io (hourly, with a grace period) and
set `HEALTHCHECK_URL` in the crontab to be emailed if runs stop or fail.

## Updating

```bash
sudo -iu freshies
cd ~/around-the-grounds && git pull && uv sync --no-dev
```

`run.sh` never changes the environment itself (`uv run --no-sync`), so run
`uv sync` after every pull.

## Off-season

After October, change the cron line to daily (e.g. `7 9 * * *`) or comment it
out. The page already handles "no fresh-hop beers found".
