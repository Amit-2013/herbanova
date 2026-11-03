# Running the frontend and backend as separate servers

Date: 3 November 2026
Branch: `feature/gap-closure`
Status: verified on loopback against the disposable test database. Not a
production web server.

The application is two processes. The **backend** owns the database, the
session cookie, permissions and every `/api` route. The **frontend** serves the
plain static files in `static/` and forwards `/api`, `/docs`, `/openapi.json`
and `/redoc` to the backend. Because the browser talks to one origin, the
session cookie stays first-party and the JavaScript keeps its relative URLs.

## 1. Start the backend

```bash
python scripts/run_backend.py
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. Use `0.0.0.0` only on a trusted LAN. |
| `--port` | `8000` | Port. |
| `--workers` | `1` | Worker processes. The e-mail worker is a separate process. |
| `--reload` | off | Reload on code changes (development only; forces one worker). |

`DATABASE_URL` and `APP_ENV` come from `.env` as before. The backend is the only
process that writes the database.

## 2. Start the frontend

In a second terminal:

```bash
python scripts/run_frontend.py
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. |
| `--port` | `3000` | Port. |
| `--backend` | `http://127.0.0.1:8000` | Backend base URL to proxy to. |

Open `http://127.0.0.1:3000/`. The root serves `static/index.html`; `/ui/` is
also accepted. `scripts/run_frontend.py` uses only the Python standard library,
so no extra package is installed for it.

If the backend runs on another port, point the frontend at it:

```bash
python scripts/run_backend.py --port 8030
python scripts/run_frontend.py --port 3030 --backend http://127.0.0.1:8030
```

## 3. What is proxied

| Path | Served by |
|---|---|
| `/`, `/ui/…`, JS, CSS, images | frontend, from `static/` |
| `/api/…` | backend, unchanged |
| `/docs`, `/openapi.json`, `/redoc` | backend, unchanged |

Every method (`GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`) is
forwarded for `/api`. An API error status is passed back as the API's answer,
not turned into a frontend error. Only if the backend cannot be reached at all
does the frontend answer **502** with a message naming the backend address and
telling you to start `scripts/run_backend.py`.

Static paths are normalised before use, and a path that would climb out of
`static/` is refused with **403** or **404**. The file server sends
`Cache-Control: no-cache`, so a browser reload always picks up the current
build.

## 4. The cookie and `APP_ENV`

The session cookie is `HttpOnly`, `SameSite=Lax` and **`Secure` whenever
`APP_ENV` is not `local`**. `.env` currently says `APP_ENV=production`, so:

- `http://localhost:3000/` and `http://127.0.0.1:3000/` work in Chrome: loopback
  is treated as a trustworthy origin and the `Secure` cookie is kept.
- A plain-HTTP address that is **not** loopback (for example a LAN IP) silently
  drops the cookie. Sign-in answers 200, then `/api/auth/me` stays 401.
- For plain-HTTP testing on a LAN, start both processes with `APP_ENV=local`
  so the cookie is not marked `Secure`. Do not do this on a real deployment.

In production, terminate TLS in front of the frontend (a reverse proxy such as
Caddy or nginx) and keep `APP_ENV=production`.

## 5. Verified behaviour

The split was exercised on 3 November 2026 with the backend on `127.0.0.1:8030`
(disposable test database, `APP_ENV=local`) and the frontend on
`127.0.0.1:3030`:

- `/` and `/ui/` returned the SPA; `app.js`, `styles.css` and the other static
  files returned 200 with the correct content types.
- `/api/auth/me` through the proxy returned 401 before sign-in and 200 after,
  so the session cookie survived the proxy.
- `/docs` and `/openapi.json` were proxied.
- Stopping the backend made the frontend answer **502** with the "start
  scripts/run_backend.py" message instead of a stack trace.
- `/../.env` and encoded traversal variants were refused (404), never served.

**Not verified:** a production reverse proxy, TLS termination, Windows service
installation and multi-worker deployment. Those are deployment work, not
application code, and were not run.

## 6. Related reading

- [README.md](../README.md) — project start-up and environment.
- [user-manual/00-quick-start.md](user-manual/00-quick-start.md) — sign-in,
  sessions and the messages a user sees.
- [DECISIONS.md](DECISIONS.md) D-44 — why the two processes are kept.
