"""Compatibility import; use matsugit.publish."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.publish')
