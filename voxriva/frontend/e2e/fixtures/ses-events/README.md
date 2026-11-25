These public synthetic test fixtures have no connection to AWS or production keys.
The private key signs local SNS envelopes; only certificate HTTP retrieval is doubled.
Production verify_sns performs canonicalization, timestamp, trusted URL and RSA signature checks.
The certificate has a fixed 2020–2100 validity window to avoid time-sensitive fixture expiry.
Never use this key/certificate for real credentials.
