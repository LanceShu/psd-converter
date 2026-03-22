# PSD UI Converter

A powerful PSD (Photoshop Document) to UI JSON converter powered by MCP (Model Context Protocol). Extracts structured metadata from PSD files and converts them into semantic, production-ready UI component definitions.

## Overview

This tool parses PSD files and outputs a well-organized JSON structure containing:

- **Layer hierarchy** — Nested layer tree with names, types, and visibility
- **Layout inference** — Flexbox layout properties (direction, alignment, gap, padding)
- **CSS styles** — Colors, gradients, shadows, borders, typography
- **Design tokens** — Normalized colors, font sizes, and font families
- **Image assets** — Exported PNG assets from smart objects and marked layers

## Features

- **Smart layer parsing** — Supports text, groups, smart objects, shapes, and pixel layers
- **Gradient extraction** — Linear, radial, and conic gradients with accurate stop positions
- **Shadow effects** — Drop shadows and inner shadows with blend modes
- **Layout inference** — Automatically detects flexbox direction, alignment, and spacing
- **Mask support** — Clipping masks and layer masks with export capability
- **Blend modes** — Full support for PSD blend modes (multiply, screen, overlay, etc.)
- **Design token collection** — Aggregates and normalizes design system values
- **MCP integration** — Works as MCP tools for AI-assisted workflows

## MCP Tools

This package provides two MCP tools for integration with AI coding assistants:

### parse_psd_to_json

Parses a PSD file and outputs structured JSON data.

```python
parse_psd_to_json(
    input_path: str,      # PSD file absolute path (required)
    output_json: str = None,  # JSON output path (optional)
    output_assets: str = "assets"  # Assets directory (default: "assets")
)
```

Returns:
- `json_path`: Path to the generated JSON file
- `assets_dir`: Path to exported assets directory
- `summary`: Statistics including canvas size, total layers, colors count, font families
- `success`: Boolean indicating success/failure

### export_psd_images

Exports image resources from a PSD file to a specified directory.

```python
export_psd_images(
    input_path: str,      # PSD file absolute path (required)
    output_assets: str = "assets"  # Assets directory (default: "assets")
)
```

Returns:
- `images`: List of exported images with name, path, and layer_id
- `output_dir`: Path to exported assets directory
- `success`: Boolean indicating success/failure

## CLI Usage

```bash
# Parse PSD and export assets
python -m src.psd_converter.psd_ui_converter -i /path/to/design.psd -oa assets -oj output.json
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-i, --input` | Absolute path to PSD file | **Required** |
| `-oa, --output-assets` | Directory for exported image assets | `assets` |
| `-oj, --output-json` | Output JSON file path | `{name}_structure.json` |

### Example

```bash
python -m src.psd_converter.psd_ui_converter \
  -i /Volumes/Design/limitedTimeOffer.psd \
  -oa ./assets \
  -oj ./output/limitedTimeOffer_structure.json
```

## Output Structure

```json
{
  "meta": {
    "canvas": { "w": 1920, "h": 1080 },
    "version": "1.0"
  },
  "designTokens": {
    "colors": { "orange": "rgb(255, 131, 64)", "white": "rgb(255, 255, 255)" },
    "fontSizes": { "title": "32px", "body": "14px" },
    "fontFamilies": ["PingFang SC", "Microsoft YaHei"]
  },
  "layers": [
    {
      "id": 1,
      "name": "Background",
      "type": "group",
      "componentType": "background",
      "zIndex": 100,
      "rect": { "x": 0, "y": 0, "w": 1920, "h": 1080 },
      "layout": {
        "flexDirection": "column",
        "alignItems": "center",
        "justifyContent": "center",
        "gap": 20
      },
      "css": { "background": "linear-gradient(180deg, ...)" },
      "children": [...]
    }
  ]
}
```

## Layer Type Markers

Use these naming conventions in your PSD to guide the parser:

| Marker | Type | Description |
|--------|------|-------------|
| `@img`, `@image`, `@photo`, `@pic` | image | Export as image asset |
| `@text`, `@label`, `@txt` | text | Text layer |
| `@btn`, `@button` | button | Button element |
| `@icon` | icon | Icon asset |
| `@card` | card | Card component |
| `@bg`, `@background` | background | Background layer |

## Smart Object Markers

| Marker | Behavior |
|--------|----------|
| `@smart`, `@so` | Recursively parse nested layers |

## Running as MCP Server

To run this as an MCP server for AI integration:

```bash
# Using FastMCP
fastmcp run src.psd_converter.psd_converter_mcp:main

# Or directly
python -m src.psd_converter.psd_converter_mcp
```

## Integration

The output JSON integrates with AI-powered frontend code generation. See `skills/skills.md` for Vue 3 component generation guidelines.

## License

MIT
