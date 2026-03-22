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
PSD Converter MCP Module

MCP tools for parsing PSD files and exporting assets.
Configured via:
{
    "mcpServers": {
        "psd-converter": {
            "command": "python",
            "args": ["-m", "psd_converter_mcp"]
        }
    }
}
"""

import os
import json
from typing import Optional

from fastmcp import FastMCP

# 复用现有解析器
from src.psd_ui_converter import PSDParser

# 初始化 FastMCP
mcp = FastMCP("psd-converter")


@mcp.tool()
def export_psd_images(
    input_path: str,
    output_assets: str = "assets",
) -> dict:
    """
    导出 PSD 中的图片资源到指定目录。

    Args:
        input_path: PSD 文件的绝对路径
        output_assets: 图片资源的输出目录（默认 "assets"）

    Returns:
        包含导出结果的字典：成功导出的图片列表、输出目录路径
    """
    result = {
        "success": False,
        "images": [],
        "output_dir": output_assets,
        "error": None,
    }

    try:
        # 检查文件是否存在
        if not os.path.exists(input_path):
            result["error"] = f"PSD file not found: {input_path}"
            return result

        # 创建解析器
        parser = PSDParser(input_path, output_assets)

        # 遍历图层，导出图片
        exported = []
        for layer in _iterate_layers(parser.psd):
            if _is_image_export_target(layer):
                path = parser._export_image(layer)
                if path:
                    exported.append({
                        "name": layer.name,
                        "path": path,
                        "layer_id": layer.layer_id,
                    })

        result["success"] = True
        result["images"] = exported
        result["output_dir"] = os.path.abspath(output_assets)

    except Exception as e:
        result["error"] = str(e)

    return result


@mcp.tool()
def parse_psd_to_json(
    input_path: str,
    output_json: Optional[str] = None,
    output_assets: str = "assets",
) -> dict:
    """
    解析 PSD 文件并输出 JSON 结构化数据。

    Args:
        input_path: PSD 文件的绝对路径
        output_json: JSON 输出文件路径（默认在当前目录生成 {name}_structure.json）
        output_assets: 图片资源的输出目录（默认 "assets"）

    Returns:
        包含解析结果的字典：JSON 文件路径、设计 tokens 摘要、图层数量统计
    """
    result = {
        "success": False,
        "json_path": None,
        "assets_dir": None,
        "summary": None,
        "error": None,
    }

    try:
        # 检查文件是否存在
        if not os.path.exists(input_path):
            result["error"] = f"PSD file not found: {input_path}"
            return result

        # 处理 JSON 输出路径
        if output_json:
            json_path = os.path.abspath(output_json)
        else:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            json_path = os.path.join(os.getcwd(), f"{base_name}_structure.json")

        # 创建解析器并保存
        parser = PSDParser(input_path, output_assets)
        parser.save_json(json_path)

        # 生成摘要
        data = parser.get_data()
        summary = _generate_summary(data)

        result["success"] = True
        result["json_path"] = json_path
        result["assets_dir"] = os.path.abspath(output_assets)
        result["summary"] = summary

    except Exception as e:
        result["error"] = str(e)

    return result


def _iterate_layers(psd):
    """递归遍历所有图层"""
    for layer in psd:
        yield layer
        if layer.is_group():
            yield from _iterate_layers(layer)


def _is_image_export_target(layer) -> bool:
    """检测图层是否应该导出为图片"""
    LAYER_MARKERS = {
        "image": ["@img", "@image", "@photo", "@pic"],
        "icon": ["@icon"],
        "smartobject": [],  # 智能对象默认导出
    }

    name_lower = layer.name.lower()

    # 检查标记
    for markers in LAYER_MARKERS.values():
        for marker in markers:
            if marker in name_lower:
                return True

    # 智能对象默认导出
    if layer.kind == "smartobject":
        return True

    return False


def _generate_summary(data: dict) -> dict:
    """从解析结果生成摘要"""
    layers = data.get("layers", [])
    tokens = data.get("designTokens", {})

    def count_layers(layer_list):
        count = len(layer_list)
        for layer in layer_list:
            if layer.get("children"):
                count += count_layers(layer["children"])
        return count

    return {
        "canvas_size": data.get("meta", {}).get("canvas"),
        "total_layers": count_layers(layers),
        "colors_count": len(tokens.get("colors", {})),
        "font_families": tokens.get("fontFamilies", []),
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
