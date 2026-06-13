# Security Policy

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

## Scope

This unofficial community Database Management Hub operates **entirely offline** on local files. It:
- Makes **no network requests** of any kind
- Reads conversation `.pb` files and other local data under `~/.gemini/antigravity/` (read-only)
- Writes only to the IDE's `state.vscdb` SQLite database and `storage.json` (when using storage subcommands)
- Creates timestamped backups before any modifications (`{db}.agmercium_recovery_{timestamp}_{reason}`)

For tool usage, recovery steps, and CLI reference, see [README.md](README.md).

## Reporting a Vulnerability

If you discover a security vulnerability in this tool, please report it responsibly:

1. **Do not open a public issue.**
2. Email the maintainer directly at: **security@agmercium.com**
3. Include:
   - A clear description of the vulnerability
   - Steps to reproduce
   - Potential impact
4. You will receive a response within 48 hours.

## Known Risks

This tool intentionally modifies the Antigravity IDE's SQLite database. While automatic backups are created, users should be aware that:

- Running the tool while the IDE is open may result in the IDE overwriting the patched database
- Corrupt `.pb` files could theoretically produce malformed index entries (the tool handles this gracefully)
- The tool requires read/write access to the database file, which is a normal user-level permission

## Dependencies

This tool uses **only Python standard library modules** and has zero external dependencies, eliminating supply-chain attack vectors.
