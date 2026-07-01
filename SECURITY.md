# Security Policy

## Supported versions

`commonplace` is deployed from `main` (rolling). Security fixes land on `main`; there are no
long-lived release branches to backport to.

## Reporting a vulnerability

**Please do not open public issues for security problems.**

Report privately via GitHub's **[private vulnerability reporting](https://github.com/itsmeduncan/commonplace/security/advisories/new)**
(repository **Security** tab → **Report a vulnerability**). This is a solo-maintained project, so
responses are best-effort — please allow a reasonable window before any public disclosure.

When reporting, include: what you found, how to reproduce it, and the impact you expect.

## Threat model (read before reporting)

`commonplace` is **designed to run on a trusted private network** (a Tailscale tailnet), and that
assumption is baked into its defaults. Reports should account for this intended model:

- **The gateway requires a per-tier bearer token** (`PERSONAL_TOKEN` / `CLIENT_TOKEN`); requests
  without the right token get `401`. Separate tokens enforce **tier isolation** — a client holding
  only the client token cannot reach the personal (hosted-extraction) endpoint. This is access
  control _on top of_ the tailnet, not a replacement for it: still do **not** port-forward `:8000` /
  `:8001` / `:3000` to the public internet. The FalkorDB browser UI (`:3000`) has only its own
  password, not the gateway token.
- **Optional payload-level tier guard (defense-in-depth).** A tier can set `graphiti.reject_pattern`
  (a regex) so `add_memory` refuses content matching it — e.g. the personal/hosted tier rejecting
  confidential-tagged material. This backstops the token isolation above for the case of a client
  misconfigured with both tokens; it is opt-in and matches only what you tell it to.
- **The bundled `patch_transport_security.py` deliberately disables FastMCP's DNS-rebinding
  protection.** This is safe only because the network is the trust boundary and clients are agents,
  not browsers. The patch's docstring documents how to re-tighten it with an explicit `allowed_hosts`
  list if you need to.
- **FalkorDB (`:6379`) binds to `127.0.0.1`** on the host and is password-protected via
  `FALKORDB_PASSWORD`; it is never exposed to the tailnet.
- **Secrets live only in `.env` on the host** (gitignored). The personal tier sends text to the
  Anthropic API for extraction by design; the client tier never leaves the host.

Issues that are **in scope**: anything that breaks these guarantees — e.g. a config that leaks
`.env`, a path that sends client-tier data off-box, a way to reach a tier without its bearer token
(bypassing the gateway), or a way to reach the graphs from outside the tailnet under the documented
setup.

Issues that are **out of scope**: consequences of deploying contrary to the docs (e.g. exposing the
ports publicly, disabling the FalkorDB password).
