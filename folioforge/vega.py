"""Compatibility import; use matsugit.vega."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.vega')
