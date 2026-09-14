#!/usr/bin/env python3
"""Mock audio renderer - generates dummy FLAC file for demo"""
import json
import sys
from pathlib import Path

# Parse arguments
request_file = None
output_dir = None
for i, arg in enumerate(sys.argv):
    if arg == "--request":
        request_file = sys.argv[i + 1]
    elif arg == "--output":
        output_dir = sys.argv[i + 1]

output_path = Path(output_dir)
output_path.mkdir(parents=True, exist_ok=True)

# Create dummy FLAC file (just empty audio data)
audio_file = output_path / "audio.flac"
audio_file.write_bytes(b"fLaC" + b"\x00" * 100)  # Minimal FLAC header

print(f"✓ Rendered audio to {audio_file}")
