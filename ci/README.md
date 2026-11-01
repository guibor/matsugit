# GitHub Actions workflow (pending installation)

`tests.yml` is the repository's test workflow. It lives here because the
automation that proposed it is not allowed to write under `.github/workflows/`.
Install it with:

```sh
mkdir -p .github/workflows
git mv ci/tests.yml .github/workflows/tests.yml
git rm ci/README.md
git commit -m "Install test workflow"
```

It installs Quarto 1.10.20 (bundled Pandoc 3.10), the `charts` and `lint`
extras and Playwright Chromium, renders the synthetic fixtures the browser tests
inspect, and runs `python -m unittest discover -s tests` with the opt-in browser
tests enabled. A second job runs the Codex plugin's Node tests.
