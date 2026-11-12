# Optional dependency locks

`setup-charts` and `setup-export` install the adjacent hash-locked requirements
with binary wheels only. Startup and rendering do not run these installers.
The `.in` files are maintainer inputs, not runtime install specifications.

Regenerate intentionally, review versions and hashes, and test all supported
Python/platform combinations before releasing:

```
uv pip compile --universal --python-version 3.10 --generate-hashes --only-binary :all: --no-python-downloads matsugit/dependencies/charts.in -o matsugit/dependencies/charts.txt
uv pip compile --universal --python-version 3.10 --generate-hashes --only-binary :all: --no-python-downloads matsugit/dependencies/export.in -o matsugit/dependencies/export.txt
```

The locks include Python-version and platform markers. Unsupported wheel
combinations fail rather than compiling source or falling back to an unpinned
package. Hashes come from the registry during release preparation; runtime
installers trust the reviewed packaged lock, not a fresh version selection.

Playwright installs its version-specific Chromium build through Playwright's
own downloader. The browser archive does not have an independently pinned
SHA-256 in this package. Approved system tools and package-registry/mirror
configuration remain separate trust decisions. There is no automatic upgrade.
