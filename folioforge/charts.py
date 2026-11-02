"""Compatibility import; use matsugit.charts."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.charts')
