import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createInterface } from "node:readline";

const cli = process.argv[2];
const timeoutMs = 15000;
const fakeToken = "EXAMPLE-DO-NOT-USE";
const invalidInputs = [
  ["", "", "Set AUTO_LINUX_DESK_URL"],
  ["not a URL", "", "valid HTTP(S)"],
  ["file:///tmp/desktop", "", "must use HTTP(S)"],
  ["http://user:EXAMPLE-DO-NOT-USE@localhost", "", "without credentials"],
  ["http://localhost/?token=EXAMPLE-DO-NOT-USE", "", "without credentials"],
  ["http://localhost/#fragment", "", "without credentials"],
  ["http://localhost", "EXAMPLE-DO-NOT-USE\nInjected: true", "line breaks"],
  ["http://localhost", "EXAMPLE-DO-NOT-USE\rInjected: true", "line breaks"],
];

for (const [url, token, message] of invalidInputs) {
  const result = spawnSync(process.execPath, [cli], {
    env: { ...process.env, AUTO_LINUX_DESK_URL: url, AUTH_TOKEN: token },
    encoding: "utf8",
    timeout: timeoutMs,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  assert.ok(result.stderr.includes(message));
  assert.ok(!result.stderr.includes(fakeToken));
}

if (process.env.TEST_MCP_URL) {
  const child = spawn(process.execPath, [cli], {
    env: {
      ...process.env,
      AUTO_LINUX_DESK_URL: process.env.TEST_MCP_URL,
      AUTH_TOKEN: fakeToken,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  let stderr = "";
  let requestID = 0;
  const pending = new Map();
  child.stderr.on("data", (data) => { stderr += data; });
  const lines = createInterface({ input: child.stdout });
  lines.on("line", (line) => {
    const message = JSON.parse(line);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.error) {
      request.reject(new Error("MCP returned an error"));
      return;
    }
    request.resolve(message.result);
  });

  function request(method, params) {
    const id = ++requestID;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`MCP request timed out: ${method}`));
      }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  const closed = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("close", (code) => {
      for (const request of pending.values()) {
        clearTimeout(request.timer);
        request.reject(new Error("Bridge exited before replying"));
      }
      resolve(code);
    });
  });
  try {
    const initialized = await request("initialize", {
      protocolVersion: "2025-03-26",
      capabilities: {},
      clientInfo: { name: "desktop-bridge-check", version: "1.0.0" },
    });
    assert.ok(initialized.capabilities.tools);
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);
    const listed = await request("tools/list", {});
    assert.ok(listed.tools.some((tool) => tool.name === "desktop_list_windows"));
    assert.ok(listed.tools.some((tool) => tool.name === "desktop_keybindings"));
    const called = await request("tools/call", {
      name: "desktop_list_windows",
      arguments: {},
    });
    assert.notEqual(called.isError, true);
    assert.ok(called.content.length > 0);
  } finally {
    child.stdin.end();
    const killTimer = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
    const exitCode = await closed;
    clearTimeout(killTimer);
    lines.close();
    assert.ok(!stderr.includes(fakeToken), "Bridge must not log the authentication token");
    assert.equal(exitCode, 0, stderr);
  }
}

process.stdout.write("Bridge input and requested MCP checks passed.\n");
