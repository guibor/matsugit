"""Compatibility import; use matsugit.preview."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.preview')
