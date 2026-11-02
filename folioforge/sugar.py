"""Compatibility import; use matsugit.sugar."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.sugar')
