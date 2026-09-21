# Security reporting

Freo is preparing its first independently validated public distribution. No
release currently has a published long-term security support commitment.

Use the repository's private vulnerability reporting feature when enabled.
Before public launch, the owner must enable it or publish a monitored private
security contact here. Do not post credentials, database dumps, recovery bundles,
listener information or private station content in public issues.

For reports, include the release version, affected component, prerequisites,
impact and a minimal reproduction using test data. Keep production secrets out
of reproduction material.

Release artifacts must be signed by the designated publisher. Obtain its public
key fingerprint independently of the downloaded artifact. The updater verifies
the detached signature and complete file manifest before running release code.

See [recovery and upgrades](docs/recovery-and-upgrades.md) for encrypted backups,
isolated restore verification and maintenance recovery. Never attach public
issue reports to the private upgrade journal; it may contain host configuration.
