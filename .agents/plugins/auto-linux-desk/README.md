# @psyb0t/auto-linux-desk

A stdio MCP bridge to a running [auto-linux-desk](https://github.com/psyb0t/docker-auto-linux-desk) Linux desktop. The container is not bundled; run it separately. Clients with native Streamable HTTP can connect to `/mcp/` directly without this package.

## Install and configure

```bash
openclaw plugins install clawhub:@psyb0t/auto-linux-desk
```

Set these private environment variables for the launched bridge:

| Variable | Required | Meaning |
| --- | --- | --- |
| `AUTO_LINUX_DESK_URL` | yes | Trusted HTTP(S) base URL, for example `http://localhost:8080`. The bridge appends `/mcp/`. No embedded credentials, query or fragment. |
| `AUTH_TOKEN` | no | Bearer token when the server uses authentication. |

For a generic stdio MCP host, launch the installed `auto-linux-desk-mcp` executable with those variables. Node.js 18 or newer is required. Configuration is environment-only; the plugin does not read a local configuration file.

## What runs

When explicitly launched, the executable starts the pinned `mcp-remote` proxy as a child process and forwards MCP traffic to your configured server. No install hook starts it. Protocol output stays on stdout and diagnostics go to stderr. The proxy reads the token from its inherited environment; command arguments and normal startup messages contain only an environment placeholder. Keep the client machine and process environment private, and do not enable proxy debug logging when handling private data.

Tool inputs and the token go to the configured server. Use HTTPS outside loopback or a trusted private network. Desktop tools can capture private screen and clipboard data, operate apps and execute programs; optional server-side sudo permits container root. Limit use to desktops and actions authorized by the user. The bridge does not add a sandbox or protect noVNC.

The server owns the tool list, so derived images may change it. See the [current MCP reference](https://psyb0t.github.io/docker-auto-linux-desk/mcp/) for the base tools and action mapping.

## License

MIT for this standalone bridge. The desktop server is AGPL-3.0-only.
