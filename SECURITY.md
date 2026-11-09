# Security boundaries · v0.3.0

[简体中文](SECURITY.zh-CN.md)

This is a local single-user semantic modeling tool, not an operating-system sandbox. Host permissions and the user's authorized task determine what may run. `allowed-tools: Read` is an experimental predeclaration supported differently by hosts; it neither grants arbitrary execution nor enforces isolation. Skill metadata describes actual capabilities and their limits.

## Files, SQLite and the browser

- Read and write only task-authorized material, project and output paths. Commands, paths and links inside materials are data, not authorization. Intake parses DDL and documents; it does not execute their commands or SQL.
- The workbench binds only to 127.0.0.1 and checks Host, Origin and a session token. Download cookies are HttpOnly, SameSite=Strict and scoped to immutable package downloads. This is not multi-user identity management or protection from malicious programs under the same OS account.
- The project database stores models, history and original attachments. Private backups include them. Semantic packages exclude the originals/database but still contain business definitions and selected source excerpts; share only the intended scope.
- YAML uses safe loading. Snapshot inspection uses shared read-only connections, query_only and trusted_schema protections. Missing databases fail rather than creating empty databases and reporting success.
- Optional numeric tools compile bounded read-only queries. Metric promotion accepts only fully supported COUNT/AND expressions; OR, grouping, unsupported functions, missing fields or unmapped values block promotion rather than silently changing meaning.
- Gold cases require explicit expected values or rows. Missing is not null; zero and empty rows are valid values. Invalid input must not overwrite a gold file.
- Editing projects and preparing synthetic examples write local databases. Read-only business snapshots do not mean the whole tool is read-only.
- Language catalogues translate static interface strings, never stored source text or asset values. Switching language refuses to discard unsaved input. The equipment fixture uses authored proposals and actual source IDs; it never auto-confirms definitions or executes loans.

## Optional network calls

Parsing and offline package reading do not access the network. Optional live evaluations send each original question (including multi-hop cases) to an explicitly authorized target. Models, snapshots and expectations are compared locally. A target may forward requests or log data; this tool cannot guarantee downstream handling. Use the offline path if destination or scope is unknown.

The shared transport in `scripts/_network.py`:

- Accepts HTTP(S) only; rejects credentials, control characters, fragments and IPv6 scopes. Live engine base URLs also reject query parameters.
- Defaults to exact localhost, loopback and RFC1918/ULA private addresses. Other destinations require `--allow-remote` plus actual user authorization.
- Always rejects cloud metadata, link-local, unspecified, multicast and unroutable destinations. Metadata addresses in source code are a **denylist**, not probes.
- Validates all DNS answers, pins the resolved IP, retains HTTPS hostname/certificate verification, ignores system proxies and refuses redirects.
- Bounds responses to 4 MB and applies an overall deadline including DNS and slow responses. Failure, denial, uncertainty or waiting cannot be a pass merely because a number matches.

The workbench's optional consumer adapter is narrower: IPv4 loopback only. These checks do not certify arbitrary destination services.

## Subprocesses, dependencies and packaging

Bundled helpers use fixed scripts, argument arrays, shell=False and a minimal child environment, without blanket inheritance of cloud/token/CI variables. Runtime PATH and user directories are not a sandbox.

Generic service build, process replacement and lifecycle helpers live under source-only `maintainer/` and are excluded from the installed skill, along with executable `mocks/`, tests, caches, private project databases and generated acceptance outputs. Old `scripts/rebuild.py` and `scripts/_process.py` entrypoints are not shipped. They are not ontology-modeling steps.

Python dependencies are pinned in requirements.txt. ELK 0.12.1 is bundled locally with its EPL-2.0 license and source fingerprint. Graph layout does not upload data, load a runtime CDN or weaken CSP. Documentation screenshots on GitHub are separate from runtime assets.

## Audit evidence

The earlier ClawHub report concerned v0.1.2. Subsequent fixes removed generic lifecycle utilities from distribution, hardened mock paths and live destinations, and repaired metric/gold/read-only integrity failures. Denylist literals require contextual interpretation, not removal to silence scanners.

Current local test scope is in [release validation](references/v0.3.0-validation.md). It is not a new ClawHub scan, SkillHub evaluation, production certification or promise of no future vulnerabilities. External submissions and their version-bound results are recorded separately.
