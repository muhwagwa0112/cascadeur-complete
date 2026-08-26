# MCP client setup

The installer automatically registers Codex when the `codex` command is present.
The effective stdio command is:

```text
%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete\cascadeur-complete.exe
```

For other MCP clients, configure that executable as a local stdio server with no
arguments. Automatic installation and end-to-end support are currently limited
to Codex. Do not configure a shell wrapper that writes diagnostic output to stdout;
stdout is reserved for MCP JSON-RPC.
