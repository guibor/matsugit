"""Compatibility import; use matsugit.layout."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.layout')
