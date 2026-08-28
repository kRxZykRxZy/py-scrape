# Production checklist

1. Copy `.env.example` to `.env` and add the Google Maps credential required by the configured maps provider.
2. Keep `.env` out of git; never commit API keys.
3. Run `docker compose up -d --build` on the Raspberry Pi.
4. Open `http://PI_IP:81` from a trusted LAN device.
5. Back up `data/py_scrape.db` regularly.
6. Put the dashboard behind an authenticated reverse proxy before exposing it to the public internet.
7. Only use publicly available business contact information and comply with Google, website, privacy, and applicable UK direct-marketing rules.

## Health
`GET /health` returns a simple service/database health response.
