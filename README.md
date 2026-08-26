# Awesome Well-Tested [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> A curated list of open-source repositories with outstanding test quality, verified by coverage metrics and mutation testing.

**Why this list?** High test coverage alone is meaningless. A test suite that never fails never protects. This list recognizes repositories that go beyond line coverage and invest in *real* test quality, including mutation testing, to prove their tests actually catch bugs.

## Contents

- [Tiers](#tiers)
- [Java](#java)
- [Python](#python)
- [JavaScript / TypeScript](#javascript--typescript)
- [Go](#go)
- [Rust](#rust)
- [C# / .NET](#c--net)
- [Ruby](#ruby)
- [Other Languages](#other-languages)
- [How We Verify](#how-we-verify)

## Tiers

| Tier   | Badge                        | Criteria                                                                          |
| ------ | ---------------------------- | --------------------------------------------------------------------------------- |
| Gold   | ![Gold](badges/gold.svg)     | Line/Branch Coverage >= 80% + Mutation Testing configured + Mutation Score >= 70% |
| Silver | ![Silver](badges/silver.svg) | Line/Branch Coverage >= 80% + Mutation Testing configured (any score)             |
| Bronze | ![Bronze](badges/bronze.svg) | Line/Branch Coverage >= 80% + CI with coverage reporting                          |

## Java

| Repository                                                        | Tier                         | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ----------------------------------------------------------------- | ---------------------------- | -------- | -------------- | ------------- | ------------- |
| [crypt-data](https://github.com/astrapi69/crypt-data)             | ![Gold](badges/gold.svg)     | 100%     | 100%           | JaCoCo        | PIT           |
| [crypt-api](https://github.com/astrapi69/crypt-api)               | ![Gold](badges/gold.svg)     | 99.4%    | 100%           | JaCoCo        | PIT           |
| [mystic-crypt](https://github.com/astrapi69/mystic-crypt)         | ![Gold](badges/gold.svg)     | 99.9%    | 99%            | JaCoCo        | PIT           |
| [gen-tree](https://github.com/astrapi69/gen-tree)                 | ![Gold](badges/gold.svg)     | 98.0%    | 98%            | JaCoCo        | PIT           |
| [silly-collection](https://github.com/astrapi69/silly-collection) | ![Bronze](badges/bronze.svg) | 98.1%    | n/a            | JaCoCo        | n/a           |
| [checksum-up](https://github.com/astrapi69/checksum-up)           | ![Bronze](badges/bronze.svg) | 96.4%    | n/a            | JaCoCo        | n/a           |
| [randomizer](https://github.com/astrapi69/randomizer)             | ![Bronze](badges/bronze.svg) | 88.4%    | n/a            | JaCoCo        | n/a           |

## Python

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## JavaScript / TypeScript

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## Go

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## Rust

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## C# / .NET

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## Ruby

| Repository               | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |               |               |

## Other Languages

| Repository               | Language | Tier | Coverage | Mutation Score | Coverage Tool | Mutation Tool |
| ------------------------ | -------- | ---- | -------- | -------------- | ------------- | ------------- |
| <!-- entries go here --> |          |      |          |                |               |               |

## How We Verify

Every repository on this list is verified before inclusion:

| Step           | What happens                                                                                                                                                                                                               |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Coverage check | `scripts/verify_repo.py` reads the actual coverage percentage from the Codecov or Coveralls public API. A configured coverage tool is not enough on its own: without a number, no tier is awarded.                         |
| Tooling check  | We inspect CI config, build files and GitHub Actions workflows for coverage tools (JaCoCo, coverage.py, Istanbul, etc.) and mutation testing tools (PIT, mutmut, Stryker, cargo-mutants, go-mutesting, mutant, Infection). |
| Mutation score | Read from a Shields.io mutation badge in the README, or supplied with `--mutation-score` after running the mutation tool. No hosted service publishes mutation scores, so this step stays partly manual.                   |
| Provenance     | Each entry ships with a JSON report under `reports/` recording the tier, the numbers and where they came from. A PR without one does not get merged.                                                                       |

Repos are re-verified periodically. If a repo's test quality degrades significantly, it may be moved to a lower tier or removed.

### Recognized Tools

**Coverage:**
JaCoCo, Kover, Istanbul/nyc, coverage.py, pytest-cov, go cover, cargo-tarpaulin, SimpleCov, dotCover, OpenCover, lcov

**Mutation Testing:**
PIT (Java), mutmut (Python), cosmic-ray (Python), Stryker (JS/TS/C#), cargo-mutants (Rust), go-mutesting (Go), mutant (Ruby), Infection (PHP)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit a repository.

**Quick version:**
1. Fork this repo
2. Run `python scripts/verify_repo.py <owner/repo>` to generate a verification report
3. Add the entry to the appropriate language section
4. Submit a PR with the verification report attached
