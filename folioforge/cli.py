"""Compatibility import; use matsugit.cli."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.cli')
