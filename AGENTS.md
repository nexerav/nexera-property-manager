# AGENTS.md

Free self-hosted property manager. Flask serves the pages and the JSON file is the books. **Read `progress.md` first** for what is live. GitHub is `nexerav/nexera-property-manager`. The public pages are the [README](README.md). This file is where to edit.

This is not the Lochaitis Trust ledger (`lt.nexerav.com`, `dev.nexerav.com`), not the Nexera P/L (`pl.nexerav.com`), and not NxtDoor. Do not apply their rules or edit their folders from here. The ledger moves last.

## Where to work

The Cloud VM is the rented server `lochaitistrust.co.za` at `156.155.253.123`. This name means that rented machine, not the computer at the house. It is being cancelled. Do not keep code, books, or the only copy of a site on it.

The machine that stays is the home server `nexerav` (`192.168.68.100`). Edit there. GitHub is the sync. The directory to start Grok in is:

```text
~/work/nexera-property-manager
```

on `nexerav`. The remote must stay `git@github.com:nexerav/nexera-property-manager.git`. A push updates GitHub. A push does not restart the demo.

On 2026-11-26 that workbench clone exists only on the rented server, and `nexerav` has no GitHub SSH key, so a push from the home server is refused. Add a key on `nexerav` and clone there before the rented server is cancelled. Do not copy the rented server's private key onto the home server.

## Where the running copies are

These are on the home server `nexerav` (`192.168.68.100`). Cloudflare Tunnel `nexerav-home` publishes the names. Do not start a coding session in these directories. Do not commit on the home server.

| What | Public name | Directory on the home server |
|---|---|---|
| This app, the public demo | https://demo.nexerav.com | `/opt/nexera-demo` (code in `/opt/nexera-demo/app`, compose file `docker-compose.demo.yml`) |
| Website | https://nexerav.com, https://www.nexerav.com, https://home.nexerav.com | `/var/www/nexerav` |
| Waitlist used by the website | the form on the website | `/opt/nexera-waitlist` |

The demo container is `nexera-demo`, bound to `127.0.0.1:5090`. Nginx on `127.0.0.1:8081` proxies the public name to it. The demo data volume is `nexera-demo_nexera-demo-data`. The website is Nginx on `127.0.0.1:8080` with that docroot. The waitlist is `nexera-waitlist.service` on `127.0.0.1:5095`, and the website proxies its form there.

The website and the waitlist are not in this repository. Figma and Buffer are outside services. Keeping these public names keeps their links valid. There is nothing to host for them here.

The rented server still has the same three paths. Those are the old copies. The live site is the home server.

## Other tools use the home server too

Start every session with `git status`, `git log --oneline -5`, and `git fetch` in the workbench. If files are modified that you did not touch, or there are commits you did not make, stop and ask the owner.

Never run `git checkout -- <file>`, `git reset --hard`, `git restore`, or `git stash drop` on a file you did not change.

## Commands

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest tests.test_app -v
```

CI runs the tests and a gitleaks scan on every push and pull request. One Gunicorn worker. Do not expose port 5000 to the internet.

## Hard rules

- Never commit `.env`, `data/rental_data.json`, or real tenant books. Sample data in the repo is fictional.
- Do not print or paste `.env`. Never run `docker compose config`.
- Do not edit the live demo, the website docroot, or the waitlist as the working copy.
- Do not force-push or rewrite history.
