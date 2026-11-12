# Deliberately wrong code

Small source trees that break one architecture rule each. The scanners of
`tests/architecture/` run on them and must report every violation, which proves the
scanners can fail. Nothing here is imported or collected as a test. The files are linted
and formatted like the rest of the repository.

| Tree | Rule it breaks | Test |
|---|---|---|
| `data_ownership/` | a module names a collection or a storage prefix it does not own | `test_data_ownership.py` |
| `money/` | a `float` money field in a contract; `round(`, `Decimal(` and arithmetic on `*_cents` outside `pricing` | `test_money_rules.py` |
| `boundaries/` | cross-module imports past `contracts.py`, a domain importing a framework, a layer pointing outward | `test_boundaries.py` |
