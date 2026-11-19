#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const MCP_PATH = "/mcp/";
const SUPPORTED_PROTOCOLS = new Set(["http:", "https:"]);
const base = process.env.AUTO_LINUX_DESK_URL;

function fail(message) {
  // stdout belongs to the MCP protocol, including on startup failures.
  console.error(`[auto-linux-desk-mcp] ${message}`);
  process.exit(1);
}

if (!base) {
  fail("Set AUTO_LINUX_DESK_URL to your running desktop server's HTTP(S) base URL.");
}

let endpoint;
try {
  endpoint = new URL(base);
} catch {
  fail("AUTO_LINUX_DESK_URL must be a valid HTTP(S) base URL.");
}
if (
  !SUPPORTED_PROTOCOLS.has(endpoint.protocol) ||
  endpoint.username ||
  endpoint.password ||
  endpoint.search ||
  endpoint.hash
) {
  fail("AUTO_LINUX_DESK_URL must use HTTP(S), without credentials, query or fragment.");
}
endpoint.pathname = `${endpoint.pathname.replace(/\/+$/, "")}${MCP_PATH}`;

const token = process.env.AUTH_TOKEN;
if (token && /[\r\n]/.test(token)) {
  fail("AUTH_TOKEN must not contain line breaks.");
}

const require = createRequire(import.meta.url);
let proxyEntry;
try {
  proxyEntry = require.resolve("mcp-remote/dist/proxy.js");
} catch {
  fail("The pinned mcp-remote dependency is missing. Reinstall the bridge package.");
}

const args = [proxyEntry, endpoint.href, "--transport", "http-only"];
if (endpoint.protocol === "http:") {
  args.push("--allow-http");
}
if (token) {
  // The proxy logs header arguments before expanding environment placeholders.
  args.push("--header", "Authorization: Bearer ${AUTH_TOKEN}");
}
args.push(...process.argv.slice(2));

const result = spawnSync(process.execPath, args, { stdio: "inherit" });
if (result.error) {
  fail("Could not start the MCP proxy.");
}
process.exit(result.status ?? 1);
