"""Gunicorn config for StockTrace on low-spec VPS (1H2G).

systemd already drops privileges with User=www — do NOT set user/group here.
"""
import multiprocessing
import os

# Self-contained: works whether ExecStart passes the app or only -c
chdir = '/opt/stocktrace/backend'
wsgi_app = 'StockTrace.wsgi:application'

bind = '127.0.0.1:8000'
# 1H2G: single worker saves RAM; threads handle concurrent short requests
workers = int(os.environ.get('GUNICORN_WORKERS', '1'))
threads = int(os.environ.get('GUNICORN_THREADS', '2'))
worker_class = 'gthread'
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOGLEVEL', 'info')
# Avoid thrashing on tiny VPS
max_requests = 500
max_requests_jitter = 50
