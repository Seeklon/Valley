"""Compile and read real FDS calculations; no surrogate values are generated here."""

from .compiler import compile_case
from .materials import material_catalog
from .parser import parse_result

__all__ = ["compile_case", "parse_result", "material_catalog"]
