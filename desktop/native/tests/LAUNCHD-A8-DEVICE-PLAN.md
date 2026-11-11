# A8 packaged macOS launchd verification (human device test)

The login item runs a native supervisor that restarts its agent child after a
nonzero exit or signal; this is the equivalent of launchd KeepAlive for the
existing SMAppService login item. Do not add a second LaunchAgent with the same
label. Run against the signed test package, not a production installation.

1. Install test package, approve Background Items, Start agent and pair.
2. `launchctl print gui/$(id -u)/com.bkty.mcptoai.device-agent`:
   record supervisor PID and child `mcptoai-agent connect` PID.
3. `kill -KILL <connect-child-pid>`: wait 2-5 seconds; verify a NEW child PID,
   same supervisor PID, one connect process, relay reconnects.
4. Repeat crash twice quickly: verify bounded backoff and no duplicate agents.
5. Desktop Quit: verify both supervisor and connect child remain online.
6. Reopen Desktop and press Stop: confirm service unregisters and both processes
   terminate; wait 35 seconds, verify neither restarts.
7. Press Start: one supervisor + one child; verify no second agent on repeated Start.
8. Stop then reboot/login: verify stopped service does not start automatically.
9. With agent running, restart Desktop and upgrade; verify no duplicate child.
10. Inspect agent-error.log and rotation, relay connection and tool approvals.

Windows: Install test package; crash only connect child, verify supervisor
restarts it; Desktop Quit leaves both; Stop kills process tree and stays stopped;
Start and repeated Start preserve singleton. Test login autostart and upgrades.

## PR #9 handover compatibility / regression matrix

- launchd PID is now the **native supervisor**, never the `connect` child.
  `ps -axo pid,ppid,command` must show one child with PPID=supervisor PID.
- A version handover stops supervisor first, waits for all managed `connect`
  children to disappear, starts the service once, and writes the version marker
  only after one supervised child is confirmed. Same-version cleanup keeps
  the sole child whose PPID matches the launchd supervisor.
- macOS parent-watch (250ms) exits the child when supervisor is SIGKILLed;
  verify no orphan `connect` after `kill -9 <supervisor-pid>`.
- Windows supervisor holds a Job Object with KILL_ON_JOB_CLOSE; verify no
  orphan connect when supervisor is forcibly terminated.
- Windows installer terminates supervisor process tree and waits for **zero**
  matching executables before replacing files; then starts supervisor once.

Device tests: (1) macOS 0.2.7 -> test build, (2) SIGKILL connect -> restart,
(3) SIGKILL supervisor -> no orphan, (4) Overview Stop -> no restart,
(5) Desktop Quit -> no agent action, (6) five Start/Stop/handover cycles with
one supervisor + one connect and no stale PIDs, (7) Windows 0.2.5 -> test
build upgrade and no locked-file/duplicate-agent errors.

## Decision after macOS 6/6 device verification

macOS supervisor removed: Login Item native launcher `execv`s connect again.
launchd observes connect PID directly. SIGTERM exits 0 (no restart);
SIGKILL reports abnormal exit and launchd restarts. No parent-watch needed.
Original PR #9 handover and duplicate cleanup semantics restored.
Windows supervisor, Job Object, and installer stop-before-replace retained.
A brief signed-package macOS regression is recommended because launcher and
handover code changed: SIGTERM no restart, SIGKILL restarts, handover one PID.
