# MCPtoAI Desktop 0.2.7 (macOS, Windows) · Linux CLI 0.2.6

Version 0.2.7 only changes how the Desktop app updates its local agent; the Linux CLI is unchanged and stays at 0.2.6.

- Safer updates: when the app updates, any agent left running from the previous version is now stopped, so only one agent stays connected.
- The app no longer restarts the background agent each time you open it.
- Server-side: if two agents from the same device connect, requests are delivered to only one of them.

Download signed installers at https://mcptoai.com/downloads/.
