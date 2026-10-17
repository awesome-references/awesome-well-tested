# Mutation score context: what makes a number comparable

A mutation score without context is not comparable. Two repositories at "95 %" can have very
different test quality depending on the mutator set, the scope, the excludes, and what the tool
counted as killed. This page lists the context worth recording with every run, shows how to get
it out of PIT (Java) and mutmut (Python), and defines a small JSON file,
`mutation-context.json`, that carries it. The same numbers from two repositories of this list's
maintainer, measured on 2026-10-16, show why:

| Repository | Raw score the tool reports | Score with context | What changed |
|---|---|---|---|
| astrapi69/manuscripta (mutmut 3.5.0) | 4824 / 5390 = 89.5 % | 96.6 % | 395 annotated equivalent mutants leave the denominator; timeouts count as not killed |
| astrapi69/mystic-crypt (PIT 1.30.0) | 98.6 % (1665 of 1688 detected) | 98.3 % strict, 99 % as PIT rounds it for the threshold | 5 timeouts are "detected" for PIT; `mutationThreshold = 99` passes on the rounded figure |

Neither number is wrong. They answer different questions, and a reader can only tell which one
when the context travels with the score.

## 1. The fields

| Field | Why it matters |
|---|---|
| Tool and version | Mutators and counting rules change between versions |
| Mutator set | PIT `DEFAULTS` versus `STRONGER` versus `ALL` moves the score by tens of points. Every PIT repository of this list's maintainer runs `DEFAULTS` (ten mutators) today, none says so explicitly |
| Scope (targets) | Which packages or modules are mutated at all |
| Excludes | Classes, methods or files left out. The main way a score gets polished |
| Result breakdown | killed, survived, no coverage, timed out, errors, skipped, equivalent |
| Tool score | What the tool itself reports (see §2 for what "detected" includes) |
| Strict score | killed / (total − equivalent − skipped): timeouts and errors count against it |
| Test strength | detected / covered mutants: measures assertion quality, not coverage |
| Commit and date | Reproducibility |
| Full or incremental run | PIT's history and mutmut's cache speed up local runs; a published number comes from a full run |
| Size | Production lines, test lines, number of tests, number of parameterized tests: a control for suite size |

## 2. Pitfalls

**Timeouts and errors.** PIT's "detected" counts `KILLED`, `TIMED_OUT`, `MEMORY_ERROR` and
`RUN_ERROR`. A mutant that makes the test suite hang or crash raises the score although no
assertion said anything about it. Report them separately. mutmut has `timeout`, `suspicious` and
`segfault`; manuscripta's own check counts all three as not killed.

**Equivalent mutants.** Some mutants do not change behaviour and cannot be killed. 100 % is
therefore rare, and above 85 to 90 % the survivors deserve a look one by one. mutmut has no
equivalence marker of its own: manuscripta keeps an annotation file (`.mutmut/equivalent.yaml`)
and its threshold check subtracts the annotated mutants from the denominator. PIT has no marker
either; `excludedMethods` is the blunt instrument. Whatever the mechanism, the count belongs in
the context file, and the rationale belongs in the repository.

**Excludes.** Generated code, DTOs without logic, `main` methods and logging are legitimate
excludes. Anything else needs a reason next to it. The ratio of excluded lines is the number a
reader wants.

**No coverage versus survived.** "No coverage" means no test runs through the line. "Survived"
means a test runs through it and asserts nothing relevant. Survived is the interesting signal;
no coverage is a coverage problem wearing a mutation badge.

**Rounding at the threshold.** PIT compares `mutationThreshold` with the rounded percentage.
1663 of 1688 detected is 98.52 %, rounds to 99, and passes a floor of 99; two more survivors fail
it. Know how much margin the floor leaves.

**Where the floor lives.** This list's verifier reads `mutationThreshold` from `build.gradle`,
`build.gradle.kts` or `pom.xml`, and mutmut floors from `pyproject.toml` or the workflow. A floor
in `gradle/mutation-testing.gradle` is enforced by Gradle and invisible to the list
(see [CONTRIBUTING](../CONTRIBUTING.md#tier-assignment)).

## 3. Java with PIT

### Gradle, Groovy DSL

What the maintainer's repositories use (crypt-data, crypt-api, mystic-crypt, gen-tree), with the
settings this page asks for added:

```groovy
plugins {
    id 'info.solidsoft.pitest' version '1.19.0'
}

pitest {
    pitestVersion = '1.30.0'
    junit5PluginVersion = '1.2.3'

    targetClasses = ['io.github.astrapi69.crypt.data.*']
    excludedClasses = ['*.generated.*']
    excludedMethods = ['toString', 'hashCode']

    mutators = ['STRONGER']            // say which set; the default is DEFAULTS, and silence hides it
    threads = 4

    outputFormats = ['HTML', 'XML']
    timestampedReports = false         // a stable path for the CI step that reads the XML

    mutationThreshold = 95             // the build fails below this; keep it in build.gradle
}
```

### Gradle, Kotlin DSL

```kotlin
plugins {
    id("info.solidsoft.pitest") version "1.19.0"
}

pitest {
    pitestVersion.set("1.30.0")
    junit5PluginVersion.set("1.2.3")
    targetClasses.set(listOf("io.github.astrapi69.*"))
    excludedClasses.set(listOf("*.generated.*"))
    mutators.set(listOf("STRONGER"))
    outputFormats.set(listOf("XML", "HTML"))
    timestampedReports.set(false)
    mutationThreshold.set(95)
}
```

### Maven

```xml
<plugin>
  <groupId>org.pitest</groupId>
  <artifactId>pitest-maven</artifactId>
  <version>1.30.0</version>
  <dependencies>
    <dependency>
      <groupId>org.pitest</groupId>
      <artifactId>pitest-junit5-plugin</artifactId>
      <version>1.2.3</version>
    </dependency>
  </dependencies>
  <configuration>
    <targetClasses><param>io.github.astrapi69.*</param></targetClasses>
    <mutators><mutator>STRONGER</mutator></mutators>
    <outputFormats><param>XML</param><param>HTML</param></outputFormats>
    <timestampedReports>false</timestampedReports>
    <mutationThreshold>95</mutationThreshold>
  </configuration>
</plugin>
```

Run: `./gradlew pitest` or `mvn test-compile org.pitest:pitest-maven:mutationCoverage`.
Report: `build/reports/pitest/mutations.xml` or `target/pit-reports/mutations.xml`. The versions
above are the ones in use on 2026-10-16; check Maven Central before copying them.

Switching `DEFAULTS` to `STRONGER` lowers the score. Measure first, then set the floor; a floor
set under `DEFAULTS` and kept under `STRONGER` turns the build red for the wrong reason.

### Reading mutations.xml

Every `<mutation>` element carries `status` (`KILLED`, `SURVIVED`, `NO_COVERAGE`, `TIMED_OUT`,
`MEMORY_ERROR`, `RUN_ERROR`) and a `<mutator>` child with the mutator's class name. From them:

- tool score = (KILLED + TIMED_OUT + MEMORY_ERROR + RUN_ERROR) / total, what PIT prints
- strict score = KILLED / (total − equivalent)
- test strength = detected / (total − NO_COVERAGE)
- the set of distinct mutators, which tells a reader the mutator group without trusting the build file

`scripts/mutation_context.py --pit build/reports/pitest/mutations.xml` does this (§5).

## 4. Python with mutmut 3.x

```toml
[tool.mutmut]
paths_to_mutate = ["src/manuscripta/exceptions.py", "src/manuscripta/paths/to_absolute.py"]
tests_dir = ["tests/unit/"]
also_copy = ["tests/fixtures/"]

[tool.manuscripta.mutation_thresholds]   # the floor this list reads for mutmut
default = 85
"src/manuscripta/exceptions.py" = 95
```

```bash
mutmut run                      # the console script; `python -m mutmut run` breaks on 3.5.0
mutmut results
mutmut export-cicd-stats        # writes mutants/mutmut-cicd-stats.json (present in 3.5.0)
```

mutmut has no selectable mutator set; its context is the version, `paths_to_mutate` and what
is left out. Its statuses are `killed`, `survived`, `no_tests`, `skipped`, `suspicious`,
`timeout`, `segfault` and `check_was_interrupted_by_user`. Two things the tool does not do and a
repository has to: equivalent mutants (an annotation file whose count enters the context) and a
threshold (a script that fails the run; the list reads `default = N` from the table that script
reads, or `MUTATION_THRESHOLD: N` in the workflow). A filtered run (`mutmut run 'pkg.module.*'`)
resets the results of every other module: the published number comes from a full run.

## 5. The context file

One `mutation-context.json` per full run, written by CI next to the tool's own report. The
schema is [`mutation-context.schema.json`](mutation-context.schema.json); the converter
`scripts/mutation_context.py` in this repository produces the file from either tool's output:

```bash
python scripts/mutation_context.py --pit build/reports/pitest/mutations.xml \
    --tool-version 1.30.0 --mutators DEFAULTS --target 'io.github.astrapi69.crypt.data.*' \
    --out build/reports/pitest/mutation-context.json

python scripts/mutation_context.py --mutmut mutants/mutmut-cicd-stats.json \
    --tool-version 3.5.0 --equivalent 395 --target src/manuscripta \
    --out mutants/mutation-context.json
```

`--repo` and `--commit` default to `GITHUB_REPOSITORY` and `GITHUB_SHA`, so a CI step needs
neither. crypt-data's run of 2026-10-16, as the converter writes it:

```json
{
  "schema_version": "1.0",
  "repository": "astrapi69/crypt-data",
  "commit": "e16b90f",
  "measured_at": "2026-10-16T11:52:00Z",
  "run_type": "full",
  "tool": {"name": "pitest", "version": "1.30.0"},
  "mutators": ["DEFAULTS"],
  "scope": {"targets": ["io.github.astrapi69.crypt.data.*"], "excludes": []},
  "results": {
    "total": 866, "killed": 860, "survived": 4, "no_coverage": 0,
    "timed_out": 2, "errors": 0, "skipped": 0, "equivalent": 0
  },
  "metrics": {
    "tool_score": 0.9954, "strict_score": 0.9931, "test_strength": 0.9954,
    "timeout_ratio": 0.0023, "error_ratio": 0.0
  }
}
```

The same file for manuscripta reads `tool_score 0.895` and `strict_score 0.966` with
`equivalent: 395`: the two numbers of the table at the top, side by side, each with the reason.
Optional blocks `coverage` (line and branch) and `size` (production lines, test lines, test
count, parameterized test count) complete the picture when a repository has them.

## 6. CI

- **When to run.** A full run on every push is fine when it is short (crypt-data: 2 minutes,
  mystic-crypt: 10 minutes, both on every push and pull request since 2026-10-16). A nightly
  schedule is the alternative for long runs (manuscripta: 2 to 8 minutes locally, nightly in
  CI). This list accepts both: a scheduled or manually dispatched workflow counts like one that
  runs on push, its latest completed run on the default branch is the one read.
- **Incremental in daily work, never for the published number.** PIT `withHistory` and mutmut's
  cache are for the developer's loop.
- **Archive the artefacts.** `mutations.xml` or `mutmut-cicd-stats.json` plus
  `mutation-context.json`, uploaded with `actions/upload-artifact` from the run that enforced
  the threshold. The context file goes in an artifact of its own, named `mutation-context`,
  because that name is what the list looks for and the tool's report can be large:

  ```yaml
  - name: Mutation context
    if: always()
    run: |
      python scripts/mutation_context.py --pit build/reports/pitest/mutations.xml \
          --tool-version 1.30.0 --mutators DEFAULTS --out build/reports/pitest/mutation-context.json
  - uses: actions/upload-artifact@v4
    with:
      name: mutation-context
      path: build/reports/pitest/mutation-context.json
  ```

- **What the list reads.** The verifier reads the floor the build enforces and shows `>= N%`.
  When the green run on the default branch that enforced it carries an artifact named
  `mutation-context`, the verifier downloads it from that run, checks the one JSON file in it
  against the schema and against the run - it has to name this repository, the commit the run
  built and a full run - and then records the file in the report under `mutation_context` and
  shows the strict score and the mutator set next to the floor:
  `>= 95% (99.3% strict, DEFAULTS)` (a mutmut row has no mutator set to name). The tier rests
  on the floor and the green run alone; the file adds what was measured behind them and
  nothing else. An artifact that is missing, has expired (90 days by default) or does not
  validate changes nothing: the row shows the floor. A context file committed to the
  repository is self-reported again, the thing Silver is for, and is ignored on purpose.

## Summary

Record per run: tool and version, mutator set, scope and excludes, the full result breakdown,
the tool's score and the strict score separately, test strength, commit, date, run type and size.
Name the mutator set explicitly, report timeouts and errors on their own, give every exclude a
reason, and let CI write the context file from the run that enforced the floor.
