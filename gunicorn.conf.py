# Gunicorn configuration for ASGI (FastAPI/Uvicorn)

# Use Uvicorn's ASGI worker instead of default sync WSGI worker
worker_class = "uvicorn.workers.UvicornWorker"

# Bind to Render's expected port
bind = "0.0.0.0:10000"

# Workers (Render free tier = limited RAM, keep low)
workers = 2

# Timeout (increase for slow startup)
timeout = 120

# Graceful timeout
graceful_timeout = 30

# Keep alive
keepalive = 5

# Access log
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Preload app for faster worker boot
preload_app = False

# Max requests per worker before restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50
