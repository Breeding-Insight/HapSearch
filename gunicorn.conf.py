"""Gunicorn configuration for the HapSearch container."""

import os


bind = f"{os.getenv('APP_HOST', '0.0.0.0')}:{os.getenv('APP_PORT', '5000')}"

# Multiple threaded workers keep the site available when a request is slow or
# a worker exits. Every value can be tuned per environment without rebuilding.
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Periodically replace workers to limit the impact of gradual memory growth.
# Jitter prevents all workers from being recycled at the same time.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "2000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "200"))

accesslog = "-"
errorlog = "-"
capture_output = True

# The existing load balancer connects to this backend over HTTPS. Local
# environments can disable TLS by leaving TLS_ENABLED unset or false.
if os.getenv("TLS_ENABLED", "false").lower() in {"true", "1", "yes"}:
    certfile = os.getenv("TLS_CERT_PATH", "/cert.pem")
    keyfile = os.getenv("TLS_KEY_PATH", "/key.pem")
