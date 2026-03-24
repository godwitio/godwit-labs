#!/usr/bin/env python3
# Copyright (c) 2026 Godwit.io
#
# Licensed under the MIT License. You may obtain a copy of the License at
#
#     https://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""
seed-data.py — Generate deterministic test files in ./data/seed/.

Files are written with content derived from their path so checksums can be
independently verified at any hop without relying solely on the state database.
"""

import hashlib
import os

# ── Configuration ─────────────────────────────────────────────────────────────

SEED_DIR         = os.path.join(os.path.dirname(__file__), "..", "data", "seed")
WRITE_CHUNK      = 1_048_576  # 1 MB — stream large files in chunks to limit memory

# (label, count, size_bytes)
FILE_SPEC = [
    ("small",  100,   65_536),          #  64 KB each  →    6.25 MB total
    ("medium",  40,   10_485_760),      #  10 MB each  →  400    MB total
    ("large",   40,  104_857_600),      # 100 MB each  → 4000    MB total
]                                        #                ≈ 4.3 GB total

# ── Helpers ───────────────────────────────────────────────────────────────────

def deterministic_chunk(path: str, chunk_index: int, size: int) -> bytes:
    """Generate up to `size` bytes of deterministic content for one chunk."""
    seed = hashlib.sha256(f"{path}:{chunk_index}".encode()).digest()
    pieces = []
    total  = 0
    piece  = seed
    while total < size:
        piece = hashlib.sha256(piece).digest()
        pieces.append(piece)
        total += len(piece)
    return b"".join(pieces)[:size]


def write_file_streaming(filepath: str, rel_path: str, size: int) -> None:
    """Write a file of `size` bytes using streaming chunks (memory-efficient)."""
    with open(filepath, "wb") as fh:
        written   = 0
        chunk_idx = 0
        while written < size:
            remaining = size - written
            chunk = deterministic_chunk(rel_path, chunk_idx, min(WRITE_CHUNK, remaining))
            fh.write(chunk)
            written   += len(chunk)
            chunk_idx += 1


def generate_files() -> list[str]:
    """Write seed files to SEED_DIR. Returns list of relative paths."""
    os.makedirs(SEED_DIR, exist_ok=True)
    paths = []
    total_bytes = 0

    for label, count, size in FILE_SPEC:
        subdir = os.path.join(SEED_DIR, label)
        os.makedirs(subdir, exist_ok=True)
        for i in range(1, count + 1):
            filename  = f"file-{i:03d}.bin"
            filepath  = os.path.join(subdir, filename)
            rel_path  = os.path.join(label, filename)
            write_file_streaming(filepath, rel_path, size)
            paths.append(filepath)
            total_bytes += size
            print(f"  created {rel_path:<32}  ({size:>12,} bytes)")

    print(f"\nSeed complete: {len(paths)} files, {total_bytes / 1_048_576:.1f} MB total")
    return paths


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Generating seed data ...")
    print(f"  Output directory: {os.path.abspath(SEED_DIR)}\n")

    generate_files()

    print("\nReady. Run to continue:")
    print("  bash scripts/init-minio.sh")
    print("  bash scripts/init-garage.sh")
    print("  bash scripts/migrate.sh")


if __name__ == "__main__":
    main()
