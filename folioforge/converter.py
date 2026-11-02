"""Compatibility import; use matsugit.converter."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.converter')
