# Production deployment

## Raspberry Pi 2 / ARMv7

1. Copy `.env.example` to `.env`.
2. Set `GOOGLE_MAPS_API_KEY` to a restricted Google Maps Platform API key with Places API (New) enabled and billing configured.
3. Run `docker compose up -d --build`.
4. Open `http://PI_IP:81` from a trusted LAN device.
5. Check `http://PI_IP:81/health` if the UI does not load.
6. Back up `data/py_scrape.db` regularly.

The Docker image is explicitly ARMv7-compatible and the application uses only lightweight Python dependencies. The Maps client uses the supported Google Places Text Search (New) HTTP API instead of browser automation or HTML scraping. Google requires an API key/billing for Places API usage and charges depend on the requested fields.

## Lead behaviour

The scraper validates the postcode as a London district, restricts Places results to the postcode's area, removes duplicate places, and excludes businesses for which Google reports a `websiteUri`. Google provides phone numbers when available. Email is left blank unless a verified public email source is added; the application never invents contact information.

## Security and compliance

Keep `.env` out of git and never expose API keys in the UI. Do not expose port 81 directly to the public internet; use authentication and an appropriate reverse proxy. Only use publicly available business contact information and comply with Google policies, website terms, privacy requirements, and applicable UK direct-marketing rules.

## Health

`GET /health` returns a simple service/database health response.
