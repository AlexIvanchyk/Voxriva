# Security policy

## Report through GitHub

For a suspected vulnerability, open the repository's
[Security tab](https://github.com/AlexIvanchyk/Voxriva/security) and use
**Advisories → Report a vulnerability** when private vulnerability reporting is
available. Send reproduction steps with fictional data, affected revisions,
impact and relevant configuration through that private report.

If GitHub does not offer a private report, open a
[minimal issue requesting a private security contact](https://github.com/AlexIvanchyk/Voxriva/issues/new)
without exploit details, affected private URLs, credentials or real message data.
Wait for the repository owner to arrange a private channel before sharing the
technical report. This policy does not imply that GitHub private reporting has
already been enabled.

Do not post credentials, keyrings, database dumps or working exploit details in
public issues or pull requests. Ordinary non-sensitive bugs belong in
[the issue tracker](https://github.com/AlexIvanchyk/Voxriva/issues).

## Supported versions and response

The current 0.1.0 source is a prerelease. No historical security maintenance
branches or response-time commitments have been announced. Include the exact
revision/image and SDK version in a report; maintainers triage reports against
current source and coordinate fixes and disclosure through GitHub.

The repository owner is [@AlexIvanchyk](https://github.com/AlexIvanchyk).
Please coordinate disclosure until a fix or mitigation can be assessed.

## Operating your installation

Operators manage their deployment's access, TLS, host security, provider accounts,
updates and database/keyring backups. See the [production runbook](PRODUCTION.md),
[MFA guide](docs/mfa.md) and [release status](docs/release-status.md).
Local tests and scan output describe their checked scope; they are not a complete
security audit or a production availability guarantee.
