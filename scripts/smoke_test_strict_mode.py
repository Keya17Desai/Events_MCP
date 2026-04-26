"""Smoke test: prove Pydantic strict mode rejects type coercion.

Without strict=True, Pydantic happily coerces "10" → 10. With strict=True,
the same input raises ValidationError. This is what protects us when an
LLM hallucinates a string in place of an int.

Run with:
    uv run python scripts/smoke_test_strict_mode.py
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError

# Mirrors the size param in tools/discovery.py
StrictSize = Annotated[int, Field(ge=1, le=50, strict=True)]
LenientSize = Annotated[int, Field(ge=1, le=50)]


def main() -> None:
    strict = TypeAdapter(StrictSize)
    lenient = TypeAdapter(LenientSize)

    # 1. Lenient mode coerces "10" → 10 (the LLM's typo passes silently)
    print(f"Lenient with '10':       {lenient.validate_python('10')} (coerced!)")

    # 2. Strict mode rejects "10"
    try:
        strict.validate_python("10")
        print("FAIL: strict mode allowed coercion")
    except ValidationError as e:
        msg = e.errors()[0]["msg"]
        print(f"Strict with '10':        rejected — {msg}")

    # 3. Strict mode still allows valid ints
    print(f"Strict with 10:          {strict.validate_python(10)} (accepted)")

    # 4. Range constraints still apply
    try:
        strict.validate_python(100)
        print("FAIL: range constraint allowed 100")
    except ValidationError as e:
        msg = e.errors()[0]["msg"]
        print(f"Strict with 100:         rejected — {msg}")


if __name__ == "__main__":
    main()
