"""
PSD Converter MCP - Entry Point

Usage:
    python -m psd_converter_mcp
    uv run psd-converter-mcp
    uvx --from git+https://github.com/LanceShu/psd-converter.git psd-converter-mcp
"""

from psd_converter_mcp import mcp

def main():
    mcp.run()

if __name__ == "__main__":
    main()
