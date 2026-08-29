# py-scrape

A lightweight Python/Jinja dashboard for background UK local-business lead research.

## Run

```bash
docker compose up -d --build
```

Open `http://localhost:81`.

## Features

- UK postcode-district input such as `UB10` or `NW7`
- Background scraping sessions with up to 3 concurrent session workers
- Single-threaded HTTP UI server
- Pause, resume and delete sessions
- Click a session to see its live lead table and logs
- Per-session `leads.csv` export
- Business name, category, phone, email and address fields
- SearXNG instance rotation using the configured public instances
- Pollinations text endpoint used as a final lead-quality heuristic
- SQLite persistence in `./data`
- No API keys required by the default configuration

## Website filtering

The application is intentionally conservative. It uses search results from multiple SearXNG instances and a second exact-name search to look for evidence of a first-party website. Directory/social/search domains are ignored during that check. Pollinations is used only as a final heuristic and never invents contact details.

Public SearXNG instances can change availability or terms at any time, so failed instances are skipped automatically.
