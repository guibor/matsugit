"""Compatibility import; use matsugit.lint."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.lint')
