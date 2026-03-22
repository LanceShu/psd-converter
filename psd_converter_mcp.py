#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "psd-tools",
#   "Pillow",
#   "scipy",
#   "fastmcp>=0.1.0",
# ]
# ///

"""
PSD Converter MCP Module - Entry Point

Usage:
    uvx --from git+https://github.com/LanceShu/psd-converter.git psd-converter-mcp

Or install locally:
    uv pip install -e .
    psd-converter-mcp
"""

import sys
import os

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from psd_converter_mcp import mcp

def main():
    mcp.run()

if __name__ == "__main__":
    main()
