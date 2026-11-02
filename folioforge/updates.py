"""Compatibility import; use matsugit.updates."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.updates')
