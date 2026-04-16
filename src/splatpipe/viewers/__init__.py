"""Viewer renderer plugins.

Splatpipe supports multiple output viewer renderers (PlayCanvas, Spark 2).
The ``ViewerRenderer`` protocol in ``base`` defines the contract; concrete
implementations live in ``playcanvas/`` and ``spark/`` subpackages.

The active renderer is selected per-project via ``Project.renderer`` (default
``"playcanvas"``). ``steps/lod_assembly.py`` reads that field and dispatches to
the matching ``ViewerRenderer.assemble()`` / ``assemble_streaming()``.
"""
