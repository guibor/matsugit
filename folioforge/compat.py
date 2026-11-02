"""Compatibility import; use matsugit.compat."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.compat')
