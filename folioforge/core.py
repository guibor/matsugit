"""Compatibility import; use matsugit.core."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.core')
