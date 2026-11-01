# Agent guidance

This repository contains a small helper for working with encrypted rclone configuration.

## Development

- Keep decrypted configuration and keys out of tool output, logs, fixtures, and commits.
- Review the `rclonedecrypt` script before changing its input/output behavior; validate with disposable encrypted fixtures.
- Load the `shell` skill before changing shell code.

## CI

- Before changing CI, inspect the current guidance in `pschmitt/ci-workflows`. Pin shared reusable workflow and action references to `@main`.
