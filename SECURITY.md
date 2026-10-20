# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| `main` | Yes |
| 0.1.x | Yes |
| Older | No |

Fixes land on `main` and in the next 0.1.x release.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability
reporting: open the repository's **Security** tab, choose **Advisories**, then
**Report a vulnerability**
([direct link](https://github.com/Resource-Hacker/obsidience/security/advisories/new)).
Do not open a public issue, discussion or pull request for a vulnerability.

Include what you can of:

- the affected component (Harness, Shell, Media or TV) and commit or version;
- the steps or a proof of concept that reproduces it;
- the impact you expect, and any configuration it depends on.

Leave secrets, personal data and your installation's private files out of the
report. Maintainers will reply in the advisory, keep you updated there and
credit you when the fix is published unless you ask otherwise.

## Scope

Obsidience is local-first: it runs on your own machine and is not a hosted
service. Its design relies on a few boundaries, and breaking any of them is in
scope:

- **Loopback services.** The Harness API listens on loopback and admits only
  local clients: it rejects non-loopback `Host` headers (against DNS
  rebinding) and cross-site browser requests. Companion services such as the
  model server and Hindsight also bind to `127.0.0.1`, and Hindsight requires
  an API key. Driving these services from the network or from an arbitrary web
  page is a vulnerability.
- **Credentials.** Secrets are held as encrypted `systemd-creds` user
  credentials and decrypted only into the process that needs them. A secret
  appearing in configuration, command arguments, logs, the Vault, SQLite state
  or the UI is a vulnerability.
- **Tool authority.** An Agent may run a Tool only through an explicit grant in
  the Article graph and the capability core's validation. Invoking a Tool
  without that grant, gaining a grant from retrieved text, a Source or model
  output, or replaying an uncertain effect is a vulnerability.
- **Desktop input and the session lock.** The Shell's session locker and the
  desktop input paths have one owner each. Bypassing the lock or injecting input
  outside those owners is a vulnerability.

Out of scope:

- vulnerabilities in upstream projects (for example Hyprland, Quickshell,
  llama.cpp, Hindsight or Jellyfin) that Obsidience does not introduce through
  its own code or patches; please report those upstream;
- attacks that already require root or the same user account on the machine;
- an installation's own machine-specific configuration, such as a service a
  user chose to publish on their network.
