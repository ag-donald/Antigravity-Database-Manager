"""
Agmercium Antigravity IDE History Recovery Tool — Source Package.

This package provides all internal modules for the recovery tool.
Import the ``main`` function from ``recovery`` to run the pipeline.
"""

from __future__ import annotations

from .constants import VERSION, TOOL_NAME

__version__ = VERSION
__all__ = ["VERSION", "TOOL_NAME"]
