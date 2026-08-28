import os
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8000'))
DB_PATH = os.getenv('DB_PATH', 'data/py_scrape.db')
MAX_LEADS = int(os.getenv('MAX_LEADS', '240'))
REQUEST_TIMEOUT = float(os.getenv('REQUEST_TIMEOUT', '12'))
POLLINATIONS_URL = os.getenv('POLLINATIONS_URL', 'https://text.pollinations.ai')
ALLOWED_STATUS = {'new', 'contacted', 'qualified', 'won', 'lost'}
