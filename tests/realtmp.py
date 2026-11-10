"""Use the real temporary directory.

On macOS the default one sits behind a symlink (/var -> /private/var). The code
under test resolves paths, so tests that build expectations from the unresolved
location would fail there for a reason that has nothing to do with the code.
"""
import os
import tempfile

tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
