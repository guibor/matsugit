"""Compatibility import; use matsugit.table_editor."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('matsugit.table_editor')
