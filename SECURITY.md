# Hermes Mobile Security Policy

Hermes Mobile is a single-tenant personal AI agent. Its posture is
layered, and the layers are not equally load-bearing.

## Reporting a Vulnerability

Report security issues privately to the repository maintainer via
[GitHub Security Advisories](https://github.com/plcunha/Hermes-Mobile/security/advisories/new).
Do not open public issues.

A useful report includes:

- Concise description and severity assessment
- Affected file paths and line ranges
- Environment (commit SHA, Python version, Flet version, Android version if applicable)
- Reproduction steps against `main`
- The trust boundary crossed

## Trust Model

### The Boundary: OS-Level Isolation

**The only security boundary against an adversarial LLM is the
operating system.** Nothing inside the agent process constitutes
containment — not any allowlist, not any pattern scanner, not any
output filter. In-process components that screen LLM output are
heuristics operating on attacker-influenced strings.

Hermes Mobile supports two isolation postures:

#### Terminal-backend isolation

A non-default terminal backend runs LLM-emitted shell commands inside
a container or sandbox. File tools also run through this backend.

This confines shell and file operations. It does not confine
code-execution, plugin loading, or skill execution within the agent
process.

#### Whole-process wrapping

Running the entire agent process tree inside a sandbox (container,
VM, or platform sandbox) confines every code path. This is the
supported posture when the agent ingests untrusted content.

### In-Process Heuristics

The following are useful accident-prevention, not boundaries:

- **Command approval** — detects common destructive shell patterns.
  A deny list over shell strings is structurally incomplete.
- **Path sandbox** — restricts file tools to allowed directories.
  A motivated output producer will find alternative paths.
- **Output redaction** — strips secret-like patterns from display.
  Not a containment mechanism.

### Credential Handling

API keys are stored in an encrypted `ProviderSecretStore`, not in the
persisted settings JSON. The secret store uses Fernet symmetric
encryption with a random key persisted in the app-private sandbox.

Credentials are not injected into subprocess environments unless
explicitly declared by the operator.

### External Surfaces

- **Gateway adapters** (Telegram, etc.) require operator-configured
  authorization before dispatching agent work.
- **Hermes Remote** requires explicit HTTPS for public hosts; plain HTTP
  is accepted only for loopback, private LAN, and Tailscale addresses.

## Scope

### In Scope

- Escape from declared OS-level isolation
- Unauthorized external-surface access
- Credential exfiltration to destinations outside the trust envelope
- Code paths that behave contrary to this policy or documented behavior

### Out of Scope

- Bypasses of in-process heuristics (command approval, path sandbox,
  output redaction)
- Prompt injection without chained isolation escape
- Consequences of the operator's chosen isolation posture
- Community-contributed skills and plugins (operator review surface)
- Public exposure without authentication, VPN, or firewall

## Deployment Hardening

- Run the agent as a non-root user
- Keep credentials in the encrypted store, never in version control
- Do not expose the gateway to the public internet without a VPN or
  Tailscale
- Review third-party skills and plugins before install
- Use the `--host 127.0.0.1` default for any network services
