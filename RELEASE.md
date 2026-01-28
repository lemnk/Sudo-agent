# Release checklist

This is a small manual checklist for maintainers.

## Before tagging

- Ensure you are on the intended commit/branch.
- Run quality gates:
  - `ruff check .`
  - `mypy src`
  - `pytest -q`
- Update `CHANGELOG.md` with:
  - date (YYYY-MM-DD)
  - user-visible changes
  - any breaking changes and migration notes
- Bump `version` in `pyproject.toml`.

## Build and verify artifacts

- Build:
  - `python -m pip install -U build`
  - `python -m build`
- Sanity-check the sdist/wheel:
  - `python -m pip install -U twine`
  - `twine check dist/*`
  - (optional) install the wheel into a clean venv and run `python -c "import sudoagent"`

## Publish

### v2.0.0 quick notes
- Version set to `2.0.0` in `pyproject.toml`.
- Artifacts built: `dist/sudoagent-2.0.0.tar.gz`, `dist/sudoagent-2.0.0-py3-none-any.whl`.
- Uploaded to PyPI (see https://pypi.org/project/sudoagent/2.0.0/).
- Token used once; rotate/revoke if desired.

### Tag the release
- `git tag v2.0.0`
- `git push origin v2.0.0`  (skip if no remote auth)

### Publish to PyPI
- If re-uploading or future releases:
  - Set env: `TWINE_USERNAME=__token__`, `TWINE_PASSWORD=<pypi-token>`
  - `twine upload dist/*`

### Smoke test from PyPI (recommended)
```bash
python -m venv .venv_release
.\.venv_release\Scripts\activate
pip install --upgrade pip
pip install sudoagent==2.0.0
python - <<'PY'
from sudoagent import SudoEngine, AllowAllPolicy
from sudoagent.ledger.jsonl import JsonlLedger
engine = SudoEngine(policy=AllowAllPolicy(), ledger=JsonlLedger("sudo_ledger.jsonl"))
@engine.guard(action="demo.echo")
def echo(x): return x
print(echo("ok"))
PY
deactivate
```

### Optional crypto extra
- `pip install "sudoagent[crypto]"`
