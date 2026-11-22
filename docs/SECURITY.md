# Security

## Secret Management

**Never commit credentials to this repository.** This includes:
- API keys (OpenRouter, Apify, Supabase, Anthropic)
- Database passwords or connection strings with credentials embedded
- SSH private keys or passwords
- Server IP addresses or hostnames that identify production infrastructure

**How to configure credentials:**
1. Copy `.env.example` to `.env` in the project root.
2. Fill in your own values in `.env`.
3. Confirm that `.env` is listed in `.gitignore` before staging any changes.

**Pre-commit scanning (recommended):** Install [gitleaks](https://github.com/gitleaks/gitleaks) or [detect-secrets](https://github.com/Yelp/detect-secrets) as a pre-commit hook to prevent accidental credential commits:

```bash
pip install detect-secrets
detect-secrets scan > .secrets.baseline
```

---

## Infrastructure

This repository contains **placeholder values only** for all infrastructure identifiers:
- Supabase URLs are shown as `https://<SUPABASE_PROJECT_ID>.supabase.co`
- VPS hostnames and IPs are shown as `<VPS_HOST>`
- Actor IDs are shown as `<APIFY_ACTOR_LINKEDIN>` / `<APIFY_ACTOR_INDEED>`

If you are deploying this system, configure your own infrastructure. Do not paste real values into documentation files, scripts, or any file that could be committed to git.

---

## Known Security Posture

The following security items are documented as open risks in the production deployment:

- **SSH root login by password** is active on the production server. This is a known risk (R-08 in [RISK_REGISTER.md](RISK_REGISTER.md)). Hardening steps: disable `PermitRootLogin`, enforce key-only authentication (`PasswordAuthentication no`), and use a non-root deployment user. These require operator action on the server.
- **API credentials were previously present in versioned documentation.** They have been removed from this repository. If you are forking from a private copy of this project, audit `git log` for credential exposure before making the repository public.

---

## Responsible Disclosure

If you discover a security vulnerability in this project:

1. **Do not open a public GitHub issue with vulnerability details.**
2. Open a GitHub issue with the title prefix `[SECURITY]` and a brief, non-sensitive description of the category of vulnerability.
3. The maintainer will respond and coordinate disclosure privately.

Please do not include exploit code, working credentials, or infrastructure details in any public report.

---

## What Not to Add to This Repository

- Real API keys or tokens of any kind
- Real server IP addresses or hostnames
- Real database connection strings with credentials
- SSH private keys
- `.env` files with real values
- Log files from production systems
- Database dumps or exports
- Any file that identifies the production infrastructure

If you are unsure whether a file is safe to commit, run a secret scanner on it before staging.
