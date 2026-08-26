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

| Repository                                                        | Tier                         | Coverage              | Mutation Score       | Param. Tests | Coverage Tool | Mutation Tool |
| ----------------------------------------------------------------- | ---------------------------- | --------------------- | -------------------- | ------------ | ------------- | ------------- |
| [crypt-data](https://github.com/astrapi69/crypt-data)             | ![Silver](badges/silver.svg) | 100%                  | 100% (self-reported) | JUnit 5      | JaCoCo        | PIT           |
| [crypt-api](https://github.com/astrapi69/crypt-api)               | ![Silver](badges/silver.svg) | 99.39% (master)       | 100% (self-reported) | JUnit 5      | JaCoCo        | PIT           |
| [mystic-crypt](https://github.com/astrapi69/mystic-crypt)         | ![Silver](badges/silver.svg) | 99.91%                | 99% (self-reported)  | JUnit 5      | JaCoCo        | PIT           |
| [gen-tree](https://github.com/astrapi69/gen-tree)                 | ![Silver](badges/silver.svg) | 98.01%                | 98% (self-reported)  | no           | JaCoCo        | PIT           |
| [silly-collection](https://github.com/astrapi69/silly-collection) | ![Bronze](badges/bronze.svg) | 98.08%                | n/a                  | no           | JaCoCo        | n/a           |
| [checksum-up](https://github.com/astrapi69/checksum-up)           | ![Bronze](badges/bronze.svg) | 96.42% (master, 2024) | n/a                  | no           | JaCoCo        | n/a           |
| [randomizer](https://github.com/astrapi69/randomizer)             | ![Bronze](badges/bronze.svg) | 88.44%                | n/a                  | JUnit 5      | JaCoCo        | n/a           |
| [iextrading4j](https://github.com/WojciechZankowski/iextrading4j) | ![Silver](badges/silver.svg) | 96.25% (2024)         | n/a                  | JUnit 5      | JaCoCo        | PIT           |

## Python

| Repository                                     | Tier                         | Coverage              | Mutation Score | Param. Tests       | Coverage Tool | Mutation Tool      |
| ---------------------------------------------- | ---------------------------- | --------------------- | -------------- | ------------------ | ------------- | ------------------ |
| [btclib](https://github.com/btclib-org/btclib) | ![Silver](badges/silver.svg) | 99.93% (dev)          | n/a            | pytest, Hypothesis | pytest-cov    | cosmic-ray         |
| [vera](https://github.com/aallan/vera)         | ![Silver](badges/silver.svg) | 94.78%                | n/a            | pytest, Hypothesis | pytest-cov    | mutmut, cosmic-ray |
| [mutmut](https://github.com/boxed/mutmut)      | ![Silver](badges/silver.svg) | 81.44% (master, 2024) | n/a            | pytest             | Codecov       | mutmut             |

## JavaScript / TypeScript

| Repository                                                                         | Tier                         | Coverage       | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ---------------------------------------------------------------------------------- | ---------------------------- | -------------- | -------------- | ------------ | ------------- | ------------- |
| [eslint-plugin-boundaries](https://github.com/javierbrea/eslint-plugin-boundaries) | ![Gold](badges/gold.svg)     | 100% (release) | 94.72%         | no           | Coveralls     | Stryker       |
| [castkodi](https://github.com/regseb/castkodi)                                     | ![Gold](badges/gold.svg)     | 100% (2022)    | 95.89%         | fast-check   | Coveralls     | Stryker       |
| [gerador-validador-cpf](https://github.com/tiagoporto/gerador-validador-cpf)       | ![Gold](badges/gold.svg)     | 97.19%         | 88.76%         | no           | Istanbul/nyc  | Stryker       |
| [accesscontrol](https://github.com/onury/accesscontrol)                            | ![Silver](badges/silver.svg) | 96.87% (2021)  | n/a            | no           | Istanbul/nyc  | Stryker       |

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

| Repository                                               | Tier                         | Coverage                          | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| -------------------------------------------------------- | ---------------------------- | --------------------------------- | -------------- | ------------ | ------------- | ------------- |
| [memoizable](https://github.com/dkubb/memoizable)        | ![Silver](badges/silver.svg) | 100% (upgrade/dependencies, 2020) | n/a            | RSpec        | SimpleCov     | mutant        |
| [homesick](https://github.com/technicalpickles/homesick) | ![Bronze](badges/bronze.svg) | 89.52% (2020)                     | n/a            | no           | Coveralls     | n/a           |

## PHP

| Repository                                                                           | Tier                         | Coverage                          | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| ------------------------------------------------------------------------------------ | ---------------------------- | --------------------------------- | -------------- | ------------ | ------------- | ------------- |
| [Porter](https://github.com/ScriptFUSION/Porter)                                     | ![Gold](badges/gold.svg)     | 100%                              | 97.91%         | PHPUnit      | PHPUnit       | Infection     |
| [doctrine-mysql-come-back](https://github.com/facile-it/doctrine-mysql-come-back)    | ![Gold](badges/gold.svg)     | 100% (master)                     | >= 90%         | PHPUnit      | PHPUnit       | Infection     |
| [Locale](https://github.com/giggsey/Locale)                                          | ![Gold](badges/gold.svg)     | 100% (1.9, 2020)                  | >= 92%         | PHPUnit      | PHPUnit       | Infection     |
| [Tree](https://github.com/nicmart/Tree)                                              | ![Gold](badges/gold.svg)     | 100%                              | >= 100%        | no           | PHPUnit       | Infection     |
| [CalendR](https://github.com/yohang/CalendR)                                         | ![Gold](badges/gold.svg)     | 100%                              | 100%           | PHPUnit      | Coveralls     | Infection     |
| [easydb](https://github.com/paragonie/easydb)                                        | ![Silver](badges/silver.svg) | 97.42% (v1.3.0, 2019)             | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [php-standard-library](https://github.com/php-standard-library/php-standard-library) | ![Gold](badges/gold.svg)     | 96.56%                            | 95.74%         | PHPUnit      | PHPUnit       | Infection     |
| [iCal](https://github.com/markuspoerschke/iCal)                                      | ![Silver](badges/silver.svg) | 93.22% (2023)                     | n/a            | PHPUnit      | PHPUnit       | Infection     |
| [stream-builder](https://github.com/Automattic/stream-builder)                       | ![Silver](badges/silver.svg) | 80.27% (dependabot/github_actio…) | n/a            | PHPUnit      | PHPUnit       | Infection     |

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
JaCoCo, Kover, Scoverage, OpenClover, Cobertura, coverage.py, pytest-cov, Istanbul/nyc, c8, Vitest coverage, Jest coverage, Deno coverage, PHPUnit, php-coveralls, SimpleCov, undercover, DeepCover, cargo-tarpaulin, cargo-llvm-cov, grcov, go cover, goveralls, gocov, octocov, go-test-coverage, coverlet, AltCover, dotCover, OpenCover, xccov, slather, Flutter coverage, ExCoveralls, HPC, gcov/lcov, OpenCppCoverage

**Mutation testing:**
PIT, Descartes, Stryker4s, mutmut, cosmic-ray, mutatest, MutPy, Stryker, Stryker.NET, Infection, Pest mutate, mutant, mutest, cargo-mutants, mutagen, go-mutesting, Gremlins, ooze, Muter, mutation_test, Muzak, MuCheck, Mull, Dextool mutate

**Parameterized and property-based tests:**
JUnit 5 `@ParameterizedTest`, JUnit 4 `@Parameterized`, TestNG `@DataProvider`, jqwik, QuickTheories, Kotest data-driven testing and property testing, ScalaCheck, ScalaTest table-driven checks, Spock `@Unroll`, `pytest.mark.parametrize`, Hypothesis, `parameterized.expand`, `unittest.subTest`, Jest/Vitest `.each`, fast-check, rstest, test-case, proptest, quickcheck, gopter, rapid, Ginkgo `DescribeTable`, `testing/quick`, rspec-parameterized, Rantly, PropCheck, xUnit `[Theory]`, NUnit `[TestCaseSource]`, MSTest `[DataTestMethod]`, FsCheck, Expecto `testProperty`, PHPUnit `@dataProvider`, Eris, BlackBox, SwiftCheck, Swift Testing `arguments`, glados, StreamData, QuickCheck, SmallCheck, Hedgehog, GoogleTest parameterized suites, Catch2 template test cases, RapidCheck, cmocka, theft

Two things are deliberately absent. Go's table-driven tests are idiomatic but
use no keyword of their own, so the Go entry detects its property-testing and
table-DSL libraries and never guesses at the idiom. RSpec's `shared_examples`
and Quick's `itBehavesLike` are not counted either: sharing example code between
contexts is reuse, not running one example across many inputs.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit a repository.

**Quick version:**
1. Fork this repo
2. Run `python scripts/verify_repo.py <owner/repo>` to generate a verification report
3. Add the entry to the appropriate language section
4. Submit a PR with the verification report attached
