"""Compatibility import; use matsugit.components."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.components')
