# Contributing to commonplace

Thanks for your interest! `commonplace` is **infrastructure** — a Docker Compose stack, two
MCP config files, a small Dockerfile, and one build-time patch. There's no application source and
no test suite, so most contributions are to **configuration, the Dockerfile/patch, CI, or docs**.

Please read the [README](README.md) first — especially the **Gotchas** section. Many of the config
quirks are load-bearing and counter-intuitive (explicit `temperature`, the bare Anthropic model
alias, the `openai`-provider-for-Ollama trick, etc.). Changing them without understanding why tends
to break ingestion silently.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

- **Keep PRs focused.** One logical change per PR.
- **Don't commit secrets.** `.env` is gitignored and must never be committed — only `.env.example`.
- **Update docs with behavior.** If you change a port, env var, model, or default, update the
  README (and `CLAUDE.md` where relevant) in the same PR.
- **Respect the security model.** This stack is designed to run on a trusted private network
  (Tailscale). It has no app-level auth and the transport patch disables DNS-rebinding protection
  on purpose. Don't add features that assume public exposure. See [SECURITY.md](SECURITY.md).

## Validate locally before opening a PR

Steps 1–4 are what CI runs, so running them first avoids a red PR:

```bash
# 1. The compose file renders (uses placeholder env from the example)
cp .env.example .env
docker compose config --quiet

# 2. The MCP configs are valid YAML
python3 -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('config/*.yaml')]"

# 3. The transport patch compiles
python3 -m py_compile patch_transport_security.py

# 4. The image builds — this is the real test that patch_transport_security.py
#    still applies cleanly to the upstream zepai/knowledge-graph-mcp:standalone image
docker build -t commonplace-mcp:ci .

# 5. If you touched the gateway, the Caddyfile is valid (not yet covered by CI)
PERSONAL_TOKEN=x CLIENT_TOKEN=x docker run --rm -e PERSONAL_TOKEN -e CLIENT_TOKEN \
  -v "$PWD/gateway/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
```

If you changed a shell script, `bash -n scripts/<name>` checks its syntax.

## Pull requests

- Open PRs against `main`. CI (**Validate config** + **Build MCP image**) must pass before merge.
- Use a clear, imperative title (e.g. "Add Ollama keep-alive to client tier"). Explain the **why**
  in the body, not just the what.
- The maintainer reviews and merges. If you don't have write access, fork and open a PR from your
  fork — that's the normal path.

## Questions / ideas

- **Questions, help, "is this possible?"** → [Discussions](https://github.com/itsmeduncan/commonplace/discussions).
- **Bugs / concrete feature requests** → [Issues](https://github.com/itsmeduncan/commonplace/issues) (use a template).

## Deploying

Maintainers deploy manually on the host (`commonplace update`, or
`git pull && docker compose up -d --build --force-recreate` by hand). There is
intentionally **no CD** — the deploy target is a private homelab, not something a public repo should
reach into. Contributors don't need any deploy access.
