# Setup

Run the image separately from the skill or plugin. Installing agent metadata does not start Docker or grant access to a desktop.

```bash
docker run -d --name desk \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5900:5900 \
  -e AUTH_TOKEN=your-token-here \
  psyb0t/auto-linux-desk:latest
```

Replace the placeholder with a private token, preferably using a private environment file. The viewer is `http://localhost:5900/`; the API is `http://localhost:8080/`. The token does not protect noVNC. Read [installation and security](https://psyb0t.github.io/docker-auto-linux-desk/installation/) for every environment variable, UID/GID, volumes and sudo.

## Claude Code and Codex

```bash
claude plugin marketplace add psyb0t/agents
claude plugin install auto-linux-desk@psyb0t

codex plugin marketplace add psyb0t/agents
codex plugin add auto-linux-desk@psyb0t
```

The Claude plugin collects the server `url` and sensitive `auth_token` when enabled. For Codex or HTTP use, provide `AUTO_LINUX_DESK_URL` and optional `AUTH_TOKEN` through private client configuration. The skill is available in a source checkout under `.agents/skills/auto-linux-desk` without installing a catalog plugin.

## Direct MCP connection

```bash
claude mcp add --transport http desk http://localhost:8080/mcp/
```

When authentication is enabled, configure the same endpoint with a private `Authorization: Bearer <token>` header. Clients that already support Streamable HTTP do not need a local proxy.

## OpenClaw

```bash
openclaw skills install @psyb0t/auto-linux-desk
openclaw plugins install clawhub:@psyb0t/auto-linux-desk
```

Set `AUTO_LINUX_DESK_URL` and optional `AUTH_TOKEN` in the bridge's environment. Node.js 18 or newer runs the bridge; it starts the pinned `mcp-remote` dependency only when launched. It forwards protocol traffic to `<base-url>/mcp/`, not to a hosted service.

Use the same container instance for the viewer, HTTP and MCP. A container does not include a web browser; install an app in a derived image or use a browser-specific image when needed.
