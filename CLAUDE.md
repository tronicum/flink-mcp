# Claude Instructions

## Bash Permissions — No Confirmation Needed

The following commands are pre-approved and must run without asking for confirmation:

- `grep` / `rg` — content search (whitelisted in settings.json)
- `cat`, `head`, `tail` — file reading
- `find` — file/directory search by name or path
- `ls`, `wc`, `sort`, `uniq`, `cut`, `echo` — standard utilities
- `sed`, `awk` — text processing
- `jq` — JSON processing
- `nslookup` — DNS lookup
- `python3`, `uv` — Python/uv execution (covers `uv run`, `uv pip`, `uv venv`, etc.)
- `jadx` — APK decompilation
- `which`, `brew` — tool discovery
- Pipe combinations of any of the above

All of the above are declared in `~/.claude/settings.json` under `permissions.allow`.

**Note on prefix matching:** Rules match on the first word of the command. `uv:*` covers all `uv run ...`, `uv pip ...` etc.
