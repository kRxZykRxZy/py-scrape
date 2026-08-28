#!/usr/bin/env python3
"""py-scrape entry point.

Run `python3 main.py` and open http://<pi-ip>:81/.
The browser UI handles postcode/count input, scraping, lead management,
activity logs and CSV export. No interactive terminal input is required.
"""
from web.app import app, db
import os


if __name__ == "__main__":
    db().close()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "81")), threaded=True)
