"""Compatibility import; use matsugit.relationships."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.relationships')
