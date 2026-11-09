# Releasing to PyPI

`kinenix`, `kinenix-hub`, and `kinenix-worker` are released together with one version number. Users install them with:

```bash
pip install kinenix              # core engine and the kinenix CLI
pip install "kinenix[worker]"    # adds kinenix-worker
pip install "kinenix[hub]"       # adds kinenix-hub (the `kinenix hub` command)
```

`kinenix-studio` is not published yet.

Publishing runs in GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml)) with **PyPI Trusted Publishing**: PyPI trusts this repository's workflow directly, so no API token is stored anywhere.

---

## 1. One-time setup

### 1.1 Trusted publishers on PyPI

Sign in to https://pypi.org with the account that owns `kinenix`.

| Project | Where | Action |
| :--- | :--- | :--- |
| `kinenix` (exists) | Your projects, then `kinenix`, then **Manage**, then **Publishing** | Add a GitHub publisher |
| `kinenix-hub` (new) | Account menu, then **Publishing** (https://pypi.org/manage/account/publishing/) | Add a **pending** publisher with project name `kinenix-hub` |
| `kinenix-worker` (new) | Same page | Add a **pending** publisher with project name `kinenix-worker` |

Use these values:

| Field | Value |
| :--- | :--- |
| Owner | `kinenix` (the GitHub organization) |
| Repository name | `kinenix` |
| Workflow name | `release.yml` |
| Environment name | `pypi` for `kinenix`, **`pypi-hub`** for `kinenix-hub`, **`pypi-worker`** for `kinenix-worker` |

A pending publisher turns into the project on the first successful upload.

Each package has its own environment, and the release workflow publishes each one in its own job: `kinenix` first, then `kinenix-hub` and `kinenix-worker`.

- A job gets one OIDC token from PyPI, scoped to the publisher that matches the job's environment. When one environment matches the publishers of several projects (for example the active publisher of `kinenix` and a pending one for `kinenix-hub`), the token is valid for only one of them and the other uploads fail with `403 Invalid API Token: OIDC scoped token is not valid for project`.
- PyPI also refuses two pending publishers with the same owner, repository, workflow, and environment ("A pending trusted publisher matching this configuration has already been registered for a different project name").

Once a project exists, a pending publisher can no longer be added for it; add the publisher in the project's own settings (**Manage**, then **Publishing**) instead.

### 1.2 Trusted publishers on TestPyPI

Repeat 1.1 on https://test.pypi.org (a separate site with its own account), with environment names **`testpypi`** for `kinenix`, **`testpypi-hub`** for `kinenix-hub`, and **`testpypi-worker`** for `kinenix-worker`. Use it to try every release before the real one.

### 1.3 GitHub environments (recommended)

The workflow creates the `pypi`, `pypi-hub`, `pypi-worker`, `testpypi`, `testpypi-hub`, and `testpypi-worker` environments on first use. To require approval before anything is published, open the repository **Settings**, then **Environments**, then **pypi**, **pypi-hub**, and **pypi-worker**, and add yourself under **Required reviewers**.

---

## 2. Making a release

Released version numbers can never be reused on PyPI or TestPyPI. If something is wrong after an upload, fix it and release the next version (for example `0.2.0b2`).

1. **Bump the version** in a pull request into `dev`. Change all of these to the same value; a test fails if they differ:
   - `__version__` in `kinenix-core/kinenix/__init__.py`, `kinenix-hub/kinenix_hub/__init__.py`, and `kinenix-worker/kinenix_worker/__init__.py`
   - `kinenix-hub>=` and `kinenix-worker>=` in the extras of `kinenix-core/pyproject.toml`
   - `kinenix>=` in the dependencies of `kinenix-hub/pyproject.toml` and `kinenix-worker/pyproject.toml`
2. **Merge `dev` into `main`** through the usual release pull request. CI builds the packages, checks their metadata, and installs them in a clean environment.
3. **Try it on TestPyPI:** in GitHub, open **Actions**, then **Release**, then **Run workflow** on `main`. When it finishes, check in a new virtual environment. Download only the three Kinenix packages from TestPyPI and take every other package from PyPI: anyone can upload to TestPyPI, and it holds broken copies of common packages (for example a `FASTAPI 1.0` that pip would pick with `--extra-index-url`).
   ```bash
   pip download --no-deps -d testpypi --index-url https://test.pypi.org/simple/ kinenix==1.0.0rc4 kinenix-hub==1.0.0rc4 kinenix-worker==1.0.0rc4
   pip install --find-links testpypi "kinenix[hub,worker]==1.0.0rc4"
   kinenix version
   kinenix-worker --version
   ```
4. **Publish to PyPI** by tagging `main`:
   ```bash
   git switch main && git pull
   git tag v1.0.0rc4
   git push origin v1.0.0rc4
   ```
   The workflow builds again, checks that the tag matches the package version, and publishes all three packages.
5. Check https://pypi.org/project/kinenix/, `kinenix-hub`, and `kinenix-worker`, then install from PyPI in a clean environment.

---

## 3. Upgrading an installation

```bash
pip install --upgrade "kinenix[hub]"      # or "kinenix[worker]"
```

On Windows, stop any running `kinenix hub` or `kinenix-worker` from that environment first. Windows locks the running `kinenix.exe`, so pip can remove the old version but fail to install the new one, leaving `kinenix` uninstalled. If that happens, stop the process and run the same command again. A folder named like `~inenix-...dist-info` left in `site-packages` by the failed attempt can be deleted.

On a Raspberry Pi running the systemd service: `sudo systemctl stop kinenix-worker`, upgrade, then `sudo systemctl start kinenix-worker`.

### Order of upgrades from 0.2.0b3 or older

1. **Upgrade every worker first.** Kinenix 0.2.0b3 and older do not know `## On Error` and `## Finally`: they run those steps as ordinary steps, so an error e-mail would be sent on every successful run. Deploy flows that use them only after every machine that runs them has 0.2.0b4 or newer (`kinenix version`), and add `> Requires: kinenix>=0.2.0b4` under their titles.
2. **Upgrade the Hub.** The first start migrates `hub.db` in place and fills in the steps, failures, and run reports of the runs already stored; on a large database that start takes longer. Back up `hub.db` first (stop the Hub, then copy it).
3. Optionally replace the Hub settings in each worker's environment with `kinenix connect http://<hub>:8080`.

Each release's changes and upgrade notes are in [CHANGELOG.md](../CHANGELOG.md).

---

## 4. What the checks cover

| Check | Where |
| :--- | :--- |
| All packages build as wheel and sdist | CI `packages` job, release workflow |
| PyPI metadata and README render (`twine check --strict`) | CI `packages` job, release workflow |
| One shared version; tag equals `v` + version | `.github/scripts/check_release.py` |
| Siblings require the same version | `kinenix-core/tests/test_repository_rules.py` |
| `kinenix[hub,worker]` installs from the built files in a clean environment, and `kinenix`, `kinenix hub`, `kinenix-worker`, and the dashboard files work | CI `packages` job |

---

## 5. The website (www.kinenix.com)

The website is a separate repository, [kinenix/kinenix-web](https://github.com/kinenix/kinenix-web): MkDocs, built and hosted by Cloudflare Pages. Every build copies `docs/` from `main` of this repository, so the site shows the documentation of the latest release, not of `dev`.

When a release pull request changes `docs/`, `README.md`, or `CHANGELOG.md` on `main`, the **Website** workflow ([`.github/workflows/website.yml`](../.github/workflows/website.yml)) asks Cloudflare Pages to build the site again. It can also be run by hand from **Actions**, then **Website**, then **Run workflow**.

One-time setup:

1. In the Cloudflare dashboard, open the Pages project of kinenix-web, then **Settings**, then **Builds**, then **Deploy hooks**, and add a hook for its production branch. Copy the URL.
2. In this repository on GitHub, open **Settings**, then **Secrets and variables**, then **Actions**, and add the secret `CLOUDFLARE_PAGES_DEPLOY_HOOK` with that URL.

Anyone with the hook URL can start a build, so keep it only in the secret. Without the secret, the workflow passes with a warning and the site is not rebuilt.
