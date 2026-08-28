# py-scrape

Lightweight London business lead finder for web agencies, designed to run on small hardware such as a Raspberry Pi 2B.

## What it does

- Starts a web dashboard with `python3 main.py`.
- Binds to `0.0.0.0:81` by default.
- Enter a London postcode district such as `UB10` or `NW10` in the browser — no terminal prompts.
- Choose how many leads to find.
- Uses the official Google Places API rather than automating/private Google Maps endpoints or bypassing CAPTCHAs.
- Filters for businesses that do not have a website listed by Google.
- Extracts public phone/email information when available.
- Stores leads in a local SQLite database under `data/`.
- Lead management: create, delete, filter, change status, and export CSV.
- Live scraper progress and activity logs.
- Optional AI enrichment through `https://text.pollinations.ai/{prompt}` for category cleanup and a short outreach angle. AI failure never blocks the scraper.

## Setup

Set a Google Places API key:

```bash
export GOOGLE_MAPS_API_KEY='YOUR_KEY'
pip3 install -r requirements.txt
python3 main.py
```

Then open `http://PI_IP:81/` from another device on your LAN.

## Docker

```bash
docker build -t py-scrape .
docker run --rm -p 81:81 -e GOOGLE_MAPS_API_KEY='YOUR_KEY' -v "$PWD/data:/app/data" py-scrape
```

The existing compose file also contains the old optional SmolLM profile; the application itself now uses Pollinations text AI and does not require a local model.

## Notes

Only use publicly available business contact information and comply with applicable Google API terms, website terms, privacy rules, and UK direct-marketing requirements. py-scrape does not attempt to bypass access controls or anti-bot systems.
