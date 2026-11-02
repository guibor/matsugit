"""Compatibility import; use matsugit.handout."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.handout')
