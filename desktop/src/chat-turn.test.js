"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");

// Exercise the actual production IPC handler with a fake child process; no
// Electron window or real Device Agent is started.
function harness() {
  const source = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  const line = source.split("\n").find(s => s.startsWith("function ensureDesktopChat(){"));
  assert.ok(line, "Production ensureDesktopChat handler must exist");
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stdin = { write() {} };
  child.killed = false;
  const waiters = new Map();
  const context = {
    desktopChatProcess: null,
    desktopChatBuffer: "",
    desktopChatWaiters: waiters,
    agentExecutable: () => ({ cmd: "mock", prefix: [], cwd: "." }),
    BrowserWindow: { getAllWindows: () => [] },
    rememberApproval() {},
    require: name => name === "child_process" ? { spawn: () => child } : require(name),
  };
  vm.createContext(context);
  vm.runInContext(line + "\nensureDesktopChat();", context);
  return { child, waiters };
}

function send(h, message) {
  h.child.stdout.emit("data", Buffer.from(JSON.stringify(message) + "\n"));
}

test("agent error followed by turn_done resolves with ok:false", async () => {
  const h = harness();
  let resolveResult;
  const result = new Promise(resolve => { resolveResult = resolve; });
  h.waiters.set("s1", { resolve: resolveResult, text: "", events: [] });
  send(h, { kind: "event", session_id: "s1", event: { type: "error", message: "Provider failed" } });
  send(h, { kind: "turn_done", session_id: "s1" });
  const value = await result;
  assert.equal(value.ok, false);
  assert.equal(value.error, "Provider failed");
  assert.equal(h.waiters.has("s1"), false);
});

test("successful empty model text uses the renderer fallback", async () => {
  const h = harness();
  let resolveResult;
  const result = new Promise(resolve => { resolveResult = resolve; });
  h.waiters.set("s2", { resolve: resolveResult, text: "", events: [] });
  send(h, { kind: "turn_done", session_id: "s2" });
  const value = await result;
  assert.equal(value.ok, true);
  assert.equal(value.text, "");

  // Evaluate the renderer's exact expression rather than a duplicated fallback.
  const renderer = fs.readFileSync(path.join(__dirname, "renderer.js"), "utf8");
  const match = renderer.match(/const answer=(r\.text\|\|[^;]+);/);
  assert.ok(match, "Renderer empty-response fallback must exist");
  const answer = vm.runInNewContext(match[1], { r: value });
  assert.equal(answer, "The model returned an empty response.");
});
