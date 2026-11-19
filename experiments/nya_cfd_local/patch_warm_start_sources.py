"""Keep the CFD warm-start field while replacing its pump source boundary values."""

from __future__ import annotations

from pathlib import Path
import re
import sys


def main(saved_u: Path, prepared_u: Path) -> None:
    saved = saved_u.read_text(encoding="ascii")
    prepared = prepared_u.read_text(encoding="ascii")
    pattern = re.compile(r"(?m)^sources\s*\{")
    saved_matches = list(pattern.finditer(saved))
    prepared_matches = list(pattern.finditer(prepared))
    if len(saved_matches) != 1 or len(prepared_matches) != 1:
        raise ValueError("Expected exactly one sources block in each U field")
    source_block = prepared[prepared_matches[0].start():]
    if source_block.count("type uniformFixedValue") != 20:
        raise ValueError("Expected 20 pump jet direction values")
    saved_u.write_text(saved[:saved_matches[0].start()] + source_block, encoding="ascii")
    if saved_u.read_text(encoding="ascii").count("type uniformFixedValue") != 20:
        raise ValueError("Warm-start pump direction patch did not persist")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
