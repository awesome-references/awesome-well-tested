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
- [PHP](#php)
- [Other Languages](#other-languages)
- [How We Verify](#how-we-verify)

## Tiers

| Tier   | Badge                        | Criteria                                                                          |
| ------ | ---------------------------- | --------------------------------------------------------------------------------- |
| Gold   | ![Gold](badges/gold.svg)     | Line/Branch Coverage >= 80% + Mutation Testing configured + Mutation Score >= 70% |
| Silver | ![Silver](badges/silver.svg) | Line/Branch Coverage >= 80% + Mutation Testing configured (any score)             |
| Bronze | ![Bronze](badges/bronze.svg) | Line/Branch Coverage >= 80% + CI with coverage reporting                          |

## Java

| Repository                                                        | Tier                         | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ----------------------------------------------------------------- | ---------------------------- | -------- | -------------- | ------------ | ------------- | ------------- |
| [crypt-data](https://github.com/astrapi69/crypt-data)             | ![Gold](badges/gold.svg)     | 100%     | 100%           | JUnit 5      | JaCoCo        | PIT           |
| [crypt-api](https://github.com/astrapi69/crypt-api)               | ![Gold](badges/gold.svg)     | 99.4%    | 100%           | JUnit 5      | JaCoCo        | PIT           |
| [mystic-crypt](https://github.com/astrapi69/mystic-crypt)         | ![Gold](badges/gold.svg)     | 99.9%    | 99%            | JUnit 5      | JaCoCo        | PIT           |
| [gen-tree](https://github.com/astrapi69/gen-tree)                 | ![Gold](badges/gold.svg)     | 98.0%    | 98%            | no           | JaCoCo        | PIT           |
| [silly-collection](https://github.com/astrapi69/silly-collection) | ![Bronze](badges/bronze.svg) | 98.1%    | n/a            | no           | JaCoCo        | n/a           |
| [checksum-up](https://github.com/astrapi69/checksum-up)           | ![Bronze](badges/bronze.svg) | 96.4%    | n/a            | no           | JaCoCo        | n/a           |
| [randomizer](https://github.com/astrapi69/randomizer)             | ![Bronze](badges/bronze.svg) | 88.4%    | n/a            | no           | JaCoCo        | n/a           |
| [iextrading4j](https://github.com/WojciechZankowski/iextrading4j) | ![Silver](badges/silver.svg) | 96.25%   | n/a            | JUnit 5      | JaCoCo        | PIT           |

## Python

| Repository                                     | Tier                         | Coverage | Mutation Score | Param. Tests       | Coverage Tool | Mutation Tool      |
| ---------------------------------------------- | ---------------------------- | -------- | -------------- | ------------------ | ------------- | ------------------ |
| [btclib](https://github.com/btclib-org/btclib) | ![Silver](badges/silver.svg) | 99.93%   | n/a            | pytest, Hypothesis | pytest-cov    | cosmic-ray         |
| [vera](https://github.com/aallan/vera)         | ![Silver](badges/silver.svg) | 94.78%   | n/a            | pytest, Hypothesis | pytest-cov    | mutmut, cosmic-ray |
| [mutmut](https://github.com/boxed/mutmut)      | ![Silver](badges/silver.svg) | 81.44%   | n/a            | pytest             | Codecov       | mutmut             |

## JavaScript / TypeScript

| Repository                                                                         | Tier                         | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ---------------------------------------------------------------------------------- | ---------------------------- | -------- | -------------- | ------------ | ------------- | ------------- |
| [eslint-plugin-boundaries](https://github.com/javierbrea/eslint-plugin-boundaries) | ![Silver](badges/silver.svg) | 100%     | n/a            | no           | Coveralls     | Stryker       |
| [castkodi](https://github.com/regseb/castkodi)                                     | ![Silver](badges/silver.svg) | 100%     | n/a            | fast-check   | Coveralls     | Stryker       |
| [gerador-validador-cpf](https://github.com/tiagoporto/gerador-validador-cpf)       | ![Silver](badges/silver.svg) | 97.19%   | n/a            | no           | Istanbul/nyc  | Stryker       |
| [accesscontrol](https://github.com/onury/accesscontrol)                            | ![Silver](badges/silver.svg) | 96.87%   | n/a            | no           | Istanbul/nyc  | Stryker       |

## Go

| Repository               | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------ | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |              |               |               |

## Rust

| Repository               | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------ | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |              |               |               |

## C# / .NET

| Repository               | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------ | ---- | -------- | -------------- | ------------ | ------------- | ------------- |
| <!-- entries go here --> |      |          |                |              |               |               |

## Ruby

| Repository                                               | Tier                         | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| -------------------------------------------------------- | ---------------------------- | -------- | -------------- | ------------ | ------------- | ------------- |
| [memoizable](https://github.com/dkubb/memoizable)        | ![Silver](badges/silver.svg) | 100%     | n/a            | RSpec        | SimpleCov     | mutant        |
| [homesick](https://github.com/technicalpickles/homesick) | ![Bronze](badges/bronze.svg) | 89.52%   | n/a            | no           | Coveralls     | n/a           |

## PHP

| Repository                                                                           | Tier                         | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------------------------------------------------------------------ | ---------------------------- | -------- | -------------- | ------------ | ------------- | ------------- |
| [Porter](https://github.com/ScriptFUSION/Porter)                                     | ![Silver](badges/silver.svg) | 100%     | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [doctrine-mysql-come-back](https://github.com/facile-it/doctrine-mysql-come-back)    | ![Silver](badges/silver.svg) | 100%     | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [Locale](https://github.com/giggsey/Locale)                                          | ![Silver](badges/silver.svg) | 100%     | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [Tree](https://github.com/nicmart/Tree)                                              | ![Silver](badges/silver.svg) | 100%     | n/a            | no           | PHPUnit       | Infection     |
| [CalendR](https://github.com/yohang/CalendR)                                         | ![Silver](badges/silver.svg) | 100%     | n/a            | PHPUnit      | Coveralls     | Infection     |
| [easydb](https://github.com/paragonie/easydb)                                        | ![Silver](badges/silver.svg) | 97.42%   | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [php-standard-library](https://github.com/php-standard-library/php-standard-library) | ![Silver](badges/silver.svg) | 96.56%   | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [iCal](https://github.com/markuspoerschke/iCal)                                      | ![Silver](badges/silver.svg) | 93.22%   | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [stream-builder](https://github.com/Automattic/stream-builder)                       | ![Silver](badges/silver.svg) | 80.27%   | n/a            | PHPUnit      | PHPUnit       | Infection     |

## Other Languages

| Repository               | Language | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------ | -------- | ---- | -------- | -------------- | ------------ | ------------- | ------------- |
| <!-- entries go here --> |          |      |          |                |              |               |               |

## How We Verify

Every repository on this list is verified before inclusion:

| Step                | What happens                                                                                                                                                                                                                                        |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Coverage check      | `scripts/verify_repo.py` reads the actual coverage percentage from the Codecov or Coveralls public API. A configured coverage tool is not enough on its own: without a number, no tier is awarded.                                                  |
| Tooling check       | We inspect CI config, build files and GitHub Actions workflows for coverage tools (JaCoCo, coverage.py, Istanbul, etc.) and mutation testing tools (PIT, mutmut, Stryker, cargo-mutants, go-mutesting, mutant, Infection).                          |
| Mutation score      | Read from a Shields.io mutation badge in the README, or supplied with `--mutation-score` after running the mutation tool. No hosted service publishes mutation scores, so this step stays partly manual.                                            |
| Parameterized tests | Repository-scoped code search looks for parameterized and property-based tests. Coverage cannot express this: a function exercised across many inputs is tested harder than one exercised once. Reported, not scored - it does not decide the tier. |
| Provenance          | Each entry ships with a JSON report under `reports/` recording the tier, the numbers and where they came from. A PR without one does not get merged.                                                                                                |

Entries are re-verified weekly. An entry that no longer clears the bar is removed quietly: the list records that it qualified, never that it stopped. An entry that moves between tiers is rewritten to the tier it holds now, with no note of what it held before. This list exists to point at software that is well tested, not to publish a verdict on software that is not.

### Recognized Tools

**Coverage:**
JaCoCo, Kover, Istanbul/nyc, coverage.py, pytest-cov, PHPUnit, go cover, cargo-tarpaulin, SimpleCov, dotCover, OpenCover, lcov

**Mutation Testing:**
PIT (Java), mutmut (Python), cosmic-ray (Python), Stryker (JS/TS/C#), cargo-mutants (Rust), go-mutesting (Go), mutant (Ruby), Infection (PHP)

**Parameterized and property-based tests:**
JUnit 5 `@ParameterizedTest`, JUnit 4 `@Parameterized`, jqwik, Kotest property testing, Spock `@Unroll`, `pytest.mark.parametrize`, Hypothesis, Jest/Vitest `.each`, fast-check, rstest, proptest, quickcheck, RSpec shared examples, Rantly, xUnit `[Theory]`, NUnit `[TestCase]`, FsCheck, PHPUnit `@dataProvider`

Go is missing from that list on purpose. Table-driven tests are idiomatic there but use no keyword of their own, so any marker would be guesswork. Go entries show `n/a` rather than a false negative.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit a repository.

**Quick version:**
1. Fork this repo
2. Run `python scripts/verify_repo.py <owner/repo>` to generate a verification report
3. Add the entry to the appropriate language section
4. Submit a PR with the verification report attached
