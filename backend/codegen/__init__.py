"""Backend → frontend type codegen.

The pydantic models emitted here are the single source of truth for the
TypeScript DTOs that the frontend consumes. The committed snapshot at
``shared_types.schema.json`` is the contract both sides agree on; the
drift-guard in ``tests/test_shared_types_schema.py`` fails the build on drift
so backend and frontend cannot diverge silently.
"""
