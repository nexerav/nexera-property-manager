# progress.md

Current state of the Nexera property manager, for the next person or LLM. Read this, then `AGENTS.md`. **Updated: 2026-11-26.** If the date here is old, check `git log` before trusting it.

## What this is

The free self-hosted app in this repository. The public demo and the marketing website run on the home server `nexerav`. GitHub is `nexerav/nexera-property-manager` and is the sync for the code. The rented server `lochaitistrust.co.za` (`156.155.253.123`) is the Cloud VM. It is being cancelled.

| | Where it runs |
|---|---|
| Workbench, start Grok here | Home server `nexerav`, `~/work/nexera-property-manager` |
| Demo | Home server, `/opt/nexera-demo`, https://demo.nexerav.com |
| Website | Home server, `/var/www/nexerav` |
| Waitlist | Home server, `/opt/nexera-waitlist` |

`lt.nexerav.com` and `dev.nexerav.com` are the private ledger. They still answer from the rented server. This repo does not deploy them.

## State at the last update

- **Workbench cloned 2026-11-26** on the rented server at `~/work/nexera-property-manager`. That clone has to move to `nexerav` before the rented server is cancelled. `nexerav` has no GitHub SSH key yet, so `git push` from the home server is refused.
- **The public names already answer from the home server.** `https://www.nexerav.com/`, `https://nexerav.com/`, and `https://demo.nexerav.com/login` returned 200. Cloudflare fronts them.
- **The running demo checkout is not this workbench.** On both machines `/opt/nexera-demo/app` is commit `4ab89de`, with uncommitted edits to `Dockerfile` and `requirements.txt`. Leave those edits where they are until a task is about shipping them. Do not copy them into the workbench as a side effect of another change.
- **The website and the waitlist have no GitHub repo.** Their files exist only in the live directories above, and in the old copies at the same paths on the Cloud VM.
- **Figma and Buffer** are outside this repo. The public names did not change.
