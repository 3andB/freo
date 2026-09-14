# Architecture and boundaries

Phase 1 has one Flask application factory in `app/__init__.py`, configuration in `app/config.py`, SQLAlchemy and Flask-Migrate in `app/extensions.py`, health routes in `app/routes/health.py`, and `wsgi.py` for Gunicorn. `/health` proves the web process responds. `/ready` runs a small PostgreSQL query and returns 503 without details on failure. No radio health is implied.

Planned flow:

```text
Internet -> Nginx -> Freo Web/API -> PostgreSQL
              |          ^               ^
              |          |           Freo Worker
              |          |                |
              |          +------------ Liquidsoap -> Icecast -> listeners
              +------------------------- controlled listener mounts
```

Nginx uses `www-data`; the web app and future scheduler/control worker use `freo`; future Liquidsoap uses `freo-playout`; future Icecast uses its package-managed `icecast2` account; PostgreSQL uses `postgres`. Only 80/443 are public by default. Gunicorn, PostgreSQL, Liquidsoap control, and Icecast source/admin backends stay private. Listener mounts will be published through controlled Nginx routes, with long-lived stream proxy behavior tested before release. The current server's `www` host remains equivalent to the apex host.

systemd owns service lifecycles. Future station configuration belongs in PostgreSQL and validated templates, rendered atomically into restricted paths. Routine playout decisions should use a private worker/control interface rather than restarting processes. Web requests must never run arbitrary sudo or shell commands, accept arbitrary Liquidsoap code, write unrestricted system configuration, or restart arbitrary units. Any privileged helper needs allowlisted operations, narrow authorization, and audit logging; `freo` must not receive broad sudo access.

Phase 2 may add `deploy/liquidsoap/` and `deploy/icecast/`, `/var/lib/freo/media`, `/var/lib/freo/playout`, `/run/freo`, and `/etc/freo` when they have concrete uses. Neither component is installed or simulated in Phase 1.
