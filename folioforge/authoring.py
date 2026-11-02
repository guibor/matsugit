"""Compatibility import; use matsugit.authoring."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.authoring')
