"""Expose the original isolated fixture without registering global override hooks."""
from .tt21_plugin import tt21_integration as tt21_integration

# Same real fixture object/lifecycle for current-head milestone consumers.
integration = tt21_integration
