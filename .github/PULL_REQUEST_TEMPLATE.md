<!-- Thanks for contributing! Keep PRs focused — one logical change. -->

## What & why

<!-- What does this change, and why? Link any related issue (e.g. Closes #12). -->

## Type of change

- [ ] Config (`config/*.yaml`, `docker-compose.yml`, `.env.example`)
- [ ] Image / build (`Dockerfile`, `patch_transport_security.py`)
- [ ] CI (`.github/workflows/`)
- [ ] Docs (`README.md`, `CLAUDE.md`, other `*.md`)

## Validation

<!-- Tick what you ran locally (these mirror CI). -->

- [ ] `cp .env.example .env && docker compose config --quiet`
- [ ] `python3 -m py_compile patch_transport_security.py`
- [ ] `docker build -t commonplace-mcp:ci .` (if the Dockerfile/patch changed)

## Checklist

- [ ] I read the relevant **Gotchas** in the README and didn't break a load-bearing quirk.
- [ ] I updated the README / `CLAUDE.md` if I changed a port, env var, model, or default.
- [ ] No secrets are committed (`.env` stays local).
