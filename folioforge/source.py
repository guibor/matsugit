"""Compatibility import; use matsugit.source."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.source')
