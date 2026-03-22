# /// script
# dependencies = [
#   "psd-tools",
#   "Pillow",
#   "scipy",
# ]
# ///

import os
import re
import json
import argparse
from typing import Dict, List, Any, Optional

try:
    from psd_tools import PSDImage
    from psd_tools.api.layers import Layer
except ImportError:
    print("[!] 错误: 未能在当前环境中找到 'psd-tools'。请执行 pip install psd-tools")
    exit(1)


# PSD 图层命名标记规范
LAYER_MARKERS = {
    "image": ["@img", "@image", "@photo", "@pic"],
    "text": ["@text", "@label", "@txt"],
    "button": ["@btn", "@button"],
    "icon": ["@icon"],
    "input": ["@input", "@field"],
    "card": ["@card"],
    "nav": ["@nav", "@navbar", "@header"],
    "footer": ["@footer"],
    "divider": ["@divider", "@line"],
    "background": ["@bg", "@background"],
}

# PSD 智能对象类型标记
SMART_OBJECT_MARKERS = ["@smart", "@so"]


def _detect_component_type(name: str, layer_type: str) -> str:
    """
    根据图层名称标记和类型检测组件语义类型

    Args:
        name: 图层名称（已转小写）
        layer_type: 图层类型

    Returns:
        组件类型字符串
    """
    # 优先根据标记检测
    for marker_type, markers in LAYER_MARKERS.items():
        for marker in markers:
            if marker in name:
                return marker_type

    # 根据图层类型推断默认类型
    type_mapping = {
        "text": "text",
        "group": "group",
        "smartobject": "image",
        "shape": "view",
        "pixel": "image",
        "other": "view",
    }
    return type_mapping.get(layer_type, "view")


def _parse_color_from_values(values: List[float], has_alpha: bool = True, fill_color_type: Optional[int] = None) -> str:
    """
    从 PSD 颜色值解析为标准 CSS 颜色字符串

    PSD FillColor.Type=1 表示 RGB 色彩空间：values = [R, G, B, Opacity]
    颜色值在 PSD 中以 0-1 浮点数存储（如 0.51471 代表 131/255）。

    Args:
        values: PSD 颜色值数组
        has_alpha: 是否有 alpha 通道
        fill_color_type: FillColor.Type（Type=1 为 RGB，其他值暂不支持）

    Returns:
        CSS 颜色字符串 (rgba 或 rgb)
    """
    if not values or len(values) < 3:
        return "rgba(0, 0, 0, 1)"

    def normalize(v: float) -> int:
        v = float(v)
        return round(v * 255) if v <= 1 else round(v)

    r = normalize(values[0] if len(values) > 0 else 0)
    g = normalize(values[1] if len(values) > 1 else 0)
    b = normalize(values[2] if len(values) > 2 else 0)

    alpha = 1.0
    if has_alpha and len(values) >= 4:
        fourth = float(values[3])
        # Opacity 通常为 1.0；若 < 1.0 则为 CSS alpha
        # 注意：Photoshop 旧版 Color 对象第4参数在 0-255 范围，
        # psd-tools 返回时已转为 0-1 浮点数
        if fourth < 1.0:
            alpha = fourth if fourth <= 1 else fourth / 255

    if alpha < 1.0:
        return f"rgba({r}, {g}, {b}, {round(alpha, 2)})"
    return f"rgb({r}, {g}, {b})"


def _get_psd_color_value(color_dict: Dict[str, Any], *keys) -> Optional[float]:
    """安全获取 PSD 颜色字典中的颜色值

    PSD 颜色字典使用字节键如 b'Rd  ', b'Grn ', b'Bl  '（4字节，带尾部空格）
    PSD 使用 descriptor.Double 类型存储数值，不是 Python float
    """
    if not color_dict:
        return None

    # 归一化目标键（大写，去空格）
    normalized_targets = set()
    for k in keys:
        key_str = k.encode("latin-1").decode("ascii", errors="ignore").upper().rstrip()
        normalized_targets.add(key_str)

    # 直接遍历所有键值对
    try:
        item_pairs = color_dict.items()
    except (AttributeError, TypeError):
        item_pairs = []

    for dict_key, val in item_pairs:
        # PSD descriptor.Double 不是 Python float，直接尝试 float() 转换
        try:
            float_val = float(val)
        except (TypeError, ValueError):
            continue
        # 归一化字典键（大写，去空格）
        dict_key_str = dict_key.decode("ascii", errors="ignore").upper().rstrip() if isinstance(dict_key, bytes) else str(dict_key).upper().rstrip()
        if dict_key_str in normalized_targets:
            return float_val

    return None


def _parse_psd_color_dict(color_dict: Dict[str, Any], opacity: float = 1.0) -> str:
    """
    从 PSD 颜色字典（键为 b'Rd  ', b'Grn ', b'Bl  '）解析为 CSS 颜色字符串

    Args:
        color_dict: PSD 颜色字典
        opacity: 不透明度 0-100

    Returns:
        CSS rgba 颜色字符串
    """
    if not color_dict:
        return "rgba(0, 0, 0, 1)"

    r = _get_psd_color_value(color_dict, "Rd", "Red") or 0
    g = _get_psd_color_value(color_dict, "Grn", "Green") or 0
    b = _get_psd_color_value(color_dict, "Bl", "Blue") or 0

    # PSD 颜色值范围通常是 0-255，但有时也是 0-1
    r, g, b = float(r), float(g), float(b)
    if r <= 1 and g <= 1 and b <= 1:
        r, g, b = r * 255, g * 255, b * 255
    r, g, b = round(r), round(g), round(b)

    alpha = round(float(opacity) / 100.0, 2) if opacity is not None else 1.0
    return f"rgba({r}, {g}, {b}, {alpha})"


def _parse_blend_mode(blend_mode_bytes: bytes) -> str:
    """
    将 PSD 混合模式字节转换为 CSS mix-blend-mode 字符串
    """
    if not blend_mode_bytes:
        return "normal"

    blend_map = {
        b"Nrml": "normal",
        b"Mltp": "multiply",
        b"Scrn": "screen",
        b"CDdg": "color-dodge",
        b"CBrn": "color-burn",
        b"Olum": "overlay",
        b"SDif": "soft-light",
        b"HDif": "hard-light",
        b"DDif": "difference",
        b"Excl": "exclusion",
        b"ShdC": "shadow",
        b"HrdL": "hard-light",
        b"SfLt": "soft-light",
        b"Dstn": "destination-out",
        b"Innr": "inner",
        b"Outr": "outer",
    }
    return blend_map.get(blend_mode_bytes, "normal")


def _get_gradient_value(gradient_data: Any, key: str, default: Any = None) -> Any:
    """
    安全获取 PSD 渐变数据中的值，支持字节键和字符串键

    PSD 渐变数据使用固定 4 字节键名（不足部分用空格填充），
    如 b'Nm  ', b'GrdF', b'Clrs', b'Clr ' 等
    """
    if not gradient_data:
        return default

    # 字符串键直接尝试
    if key in gradient_data:
        return gradient_data[key]

    # 字节键
    key_bytes = key.encode("latin-1") if isinstance(key, str) else key
    if key_bytes in gradient_data:
        return gradient_data[key_bytes]

    # PSD 固定 4 字节键名（空格填充），尝试归一化匹配
    key_norm = key_bytes.decode("ascii", errors="ignore").upper().rstrip()
    key_padded = (key_norm + "    ")[:4]

    try:
        items = gradient_data.items()
    except (AttributeError, TypeError):
        items = []

    for dict_key, val in items:
        dict_key_norm = dict_key.decode("ascii", errors="ignore").upper().rstrip() if isinstance(dict_key, bytes) else str(dict_key).upper().rstrip()
        dict_key_padded = (dict_key_norm + "    ")[:4]
        if dict_key_padded == key_padded:
            return val

    return default


def _parse_gradient(gradient_data: Dict[str, Any], angle: float = 0) -> str:
    """
    将 PSD 渐变数据解析为 CSS linear-gradient 字符串

    Args:
        gradient_data: PSD 渐变数据字典
        angle: 渐变角度（PSD 使用角度，CSS 也使用角度）

    Returns:
        CSS linear-gradient 字符串
    """
    if not gradient_data:
        return "linear-gradient(180deg, transparent, transparent)"

    # 解析颜色停止点
    colors_raw = _get_gradient_value(gradient_data, "Clrs", [])

    stops = []
    for i, color_entry in enumerate(colors_raw):
        # color_entry 是 Descriptor 或 dict，包含 Clr、Lctn 等
        # 先尝试获取内嵌的 Clr 字典
        color_dict = _get_gradient_value(color_entry, "Clr", None)

        if color_dict:
            r = _get_psd_color_value(color_dict, "Rd") or 0
            g = _get_psd_color_value(color_dict, "Grn") or 0
            b = _get_psd_color_value(color_dict, "Bl") or 0
        else:
            # 直接在 color_entry 中的颜色值
            r = _get_gradient_value(color_entry, "Rd", 0)
            g = _get_gradient_value(color_entry, "Grn", 0)
            b = _get_gradient_value(color_entry, "Bl", 0)

        # PSD 颜色值通常是 0-255，但有时也是 0-1
        r, g, b = float(r), float(g), float(b)
        if r <= 1 and g <= 1 and b <= 1:
            r, g, b = r * 255, g * 255, b * 255
        r, g, b = round(r), round(g), round(b)

        color = f"rgb({r}, {g}, {b})"

        # 位置 (0-4096 映射到 0%-100%)
        # 注意：psd-tools 返回的是 Integer/Float 类型（不是 Python int/float），
        # 用 hasattr(__float__) 或 try/except 来安全判断
        location = 0
        loc_val = _get_gradient_value(color_entry, "Lctn", 0)
        try:
            location = round(float(loc_val) / 4096 * 100, 1)
        except (TypeError, ValueError):
            pass

        stops.append(f"{color} {location}%")

    if not stops:
        stops = ["transparent 0%", "transparent 100%"]

    # 渐变类型
    grad_type = _get_gradient_value(gradient_data, "GrdF", b"Lnr ")
    grad_type_str = grad_type.decode("latin-1", errors="ignore") if isinstance(grad_type, bytes) else str(grad_type)

    # 渐变类型映射
    gradient_func = "linear-gradient"
    if "Rad" in grad_type_str:
        gradient_func = "radial-gradient"
    elif "Ang" in grad_type_str:
        gradient_func = "conic-gradient"

    # 角度: PSD 逆时针，CSS 也逆时针，所以直接用
    css_angle = angle if angle else 180
    return f"{gradient_func}({css_angle}deg, {', '.join(stops)})"


class DesignTokensCollector:
    """收集并归一化设计系统的 token"""

    def __init__(self):
        self.colors: Dict[str, str] = {}
        self.font_sizes: Dict[str, str] = {}
        self.font_families: List[str] = []
        self._font_size_counter: int = 0
        self._color_counter: int = 0

    def add_color(self, css_color: str):
        """添加颜色，自动命名归类"""
        if not css_color or css_color in self.colors.values():
            return
        # 尝试归类为语义化名称
        color_key = self._normalize_color_key(css_color)
        if color_key and color_key not in self.colors:
            self.colors[color_key] = css_color
        else:
            self.colors[f"color_{self._color_counter}"] = css_color
            self._color_counter += 1

    def _normalize_color_key(self, css_color: str) -> Optional[str]:
        """根据颜色值猜测语义化名称"""
        # 常见颜色模式匹配
        color_map = {
            "rgba(255, 255, 255": "white",
            "rgba(0, 0, 0": "black",
            "rgba(255, 0, 0": "red",
            "rgba(0, 128, 0": "green",
            "rgba(0, 0, 255": "blue",
            "rgba(255, 215, 0": "gold",
            "rgba(255, 165, 0": "orange",
            "rgba(128, 0, 128": "purple",
        }
        for pattern, name in color_map.items():
            if css_color.lower().startswith(pattern):
                return name
        return None

    def add_font_size(self, font_size: str):
        """添加字体大小，自动命名归类"""
        if not font_size or font_size in self.font_sizes.values():
            return
        # 尝试归类为语义化名称
        size_key = self._normalize_font_size_key(font_size)
        if size_key and size_key not in self.font_sizes:
            self.font_sizes[size_key] = font_size
        else:
            self.font_sizes[f"size_{self._font_size_counter}"] = font_size
            self._font_size_counter += 1

    def _normalize_font_size_key(self, font_size: str) -> Optional[str]:
        """根据字号猜测语义化名称"""
        try:
            size = int(font_size.replace("px", ""))
            if size <= 12:
                return "caption"
            elif size <= 14:
                return "body"
            elif size <= 16:
                return "bodyLarge"
            elif size <= 20:
                return "subtitle"
            elif size <= 24:
                return "title"
            elif size <= 32:
                return "h2"
            elif size <= 40:
                return "h1"
            else:
                return "display"
        except (ValueError, AttributeError):
            return None

    def add_font_family(self, font_family: str):
        """添加字体族，去重"""
        if font_family and font_family not in self.font_families:
            self.font_families.append(font_family)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "colors": self.colors,
            "fontSizes": self.font_sizes,
            "fontFamilies": self.font_families,
        }


class PSDParser:
    """
    处理 PSD 文件的元数据提取和视觉资源导出。
    将 PSD 图层映射为包含 UI 结构和 CSS 样式的结构化 JSON 格式。
    """

    # 最大递归深度，防止深层嵌套导致性能问题
    MAX_RECURSION_DEPTH = 10

    def __init__(self, file_path: str, assets_dir: str):
        # 确保资源导出目录是绝对路径
        self.assets_dir = os.path.abspath(os.path.expanduser(assets_dir))

        print(f"[*] 正在加载 PSD 文件: {file_path}")
        self.psd = PSDImage.open(file_path)

        # 创建资源文件夹
        try:
            os.makedirs(self.assets_dir, exist_ok=True)
        except OSError as e:
            raise OSError(f"Failed to create assets directory at {self.assets_dir}: {e}")

        # 初始化设计 token 收集器
        self._tokens_collector = DesignTokensCollector()

    def _get_layer_type(self, layer: Layer) -> str:
        """识别图层类型 (组、文本、智能对象、形状等)"""
        if layer.is_group():
            return "group"
        if layer.kind == "type":
            return "text"
        if layer.kind == "smartobject":
            return "smartobject"
        if layer.kind in ["shape", "pixel"]:
            return layer.kind
        return "other"

    def _export_image(self, layer: Layer) -> Optional[str]:
        """将图层导出为 PNG，并清理文件名"""
        # 移除非法字符和所有标记，确保文件名安全
        clean_name = layer.name
        for markers in LAYER_MARKERS.values():
            for marker in markers:
                clean_name = clean_name.replace(marker, "")
        clean_name = re.sub(r'[\\/*?:"<>|]', "", clean_name.strip())
        # 使用图层 ID 避免重名覆盖
        file_name = f"{clean_name}_{layer.layer_id}.png"
        file_path = os.path.join(self.assets_dir, file_name)

        # 将图层渲染为图像对象
        image = layer.composite()
        if image:
            image.save(file_path)
            return file_path
        return None

    def _extract_css(self, layer: Layer) -> Dict[str, Any]:
        """
        提取图层的 CSS 样式信息
        """
        # 1. 提取通用样式
        css: Dict[str, Any] = {
            # psd-tools 的 opacity 范围是 0-255，这里映射为 CSS 标准的 0.0-1.0
            "opacity": round(layer.opacity / 255.0, 2),
            # 提取混合模式 (例如 'multiply', 'screen')
            "mixBlendMode": (
                layer.blend_mode.name.lower()
                if hasattr(layer, "blend_mode")
                else "normal"
            ),
        }

        # 2. 提取文本专属样式
        if layer.kind == "type" and hasattr(layer, "engine_dict"):
            # 安全获取嵌套字典的辅助函数
            def safe_get(d, *keys):
                for key in keys:
                    try:
                        d = d[key]
                    except (KeyError, TypeError, IndexError):
                        return None
                return d

            try:
                # 从深层的 engine_dict 中挖掘样式表数据
                style_sheet = safe_get(
                    layer.engine_dict,
                    "StyleRun",
                    "RunArray",
                    0,
                    "StyleSheet",
                    "StyleSheetData",
                )

                if style_sheet:
                    # 获取字体大小
                    font_size = style_sheet.get("FontSize")
                    if font_size is not None:
                        font_size_str = f"{round(float(font_size))}px"
                        css["fontSize"] = font_size_str
                        self._tokens_collector.add_font_size(font_size_str)

                    # 获取字体颜色
                    # PSD FillColor 可能存储 RGB 或 CMYK，第4值可能是 opacity 或 CMYK K 通道
                    fill_color_obj = style_sheet.get("FillColor", {})
                    fill_color_values = fill_color_obj.get("Values")
                    fill_color_type = fill_color_obj.get("Type")
                    if fill_color_values and len(fill_color_values) >= 4:
                        css["color"] = _parse_color_from_values(
                            [float(v) for v in fill_color_values],
                            has_alpha=True,
                            fill_color_type=fill_color_type,
                        )
                        self._tokens_collector.add_color(css["color"])

                    # 获取行高 (LineLeading，单位是点，需要转换为倍数)
                    line_height = style_sheet.get("LineLeading")
                    if line_height is not None:
                        # 行高转换：如果有字体大小，则计算倍数；否则直接存储为 px
                        font_size = style_sheet.get("FontSize")
                        if font_size and float(font_size) > 0:
                            css["lineHeight"] = round(float(line_height) / float(font_size), 2)
                        else:
                            css["lineHeight"] = f"{round(float(line_height))}px"

                    # 获取字间距 (LetterSpacing，单位是千分之磅值)
                    letter_spacing = style_sheet.get("Tracking", style_sheet.get("FontSize"))
                    if letter_spacing is not None:
                        # Photoshop 字间距单位是千分之一 em
                        css["letterSpacing"] = round(float(letter_spacing) / 1000, 2)

                    # 获取字体族
                    font_family = safe_get(
                        layer.engine_dict,
                        "ResourceDictionary",
                        "FontSet",
                        0,
                        "Font",
                        "Name",
                    )
                    if font_family:
                        # 清理字体名称，移除 PostScript 名称等
                        font_name = str(font_family).split("-")[0].strip()
                        css["fontFamily"] = font_name
                        self._tokens_collector.add_font_family(font_name)

                    # 获取字体粗细
                    font_weight = style_sheet.get("FontStyle")
                    if font_weight:
                        weight_map = {
                            "Bold": 700,
                            "SemiBold": 600,
                            "Medium": 500,
                            "Regular": 400,
                            "Light": 300,
                            "Thin": 100,
                        }
                        css["fontWeight"] = weight_map.get(str(font_weight), 400)

            except KeyError as e:
                print(f"  [警告] 解析文本图层 '{layer.name}' 样式键缺失: {e}")
            except TypeError as e:
                print(f"  [警告] 解析文本图层 '{layer.name}' 类型错误: {e}")
            except IndexError as e:
                print(f"  [警告] 解析文本图层 '{layer.name}' 索引错误: {e}")
            except ValueError as e:
                print(f"  [警告] 解析文本图层 '{layer.name}' 值错误: {e}")

        # 3. 提取图层样式 (Layer Effects)
        self._extract_layer_effects(layer, css)

        return css

    def _extract_layer_effects(self, layer: Layer, css: Dict[str, Any]):
        """
        从 PSD Layer Effects 提取 CSS 样式
        支持: DropShadow, InnerShadow, GradientOverlay, ColorOverlay, Stroke

        效果映射:
        - DropShadow / InnerShadow -> boxShadow
        - Stroke -> border
        - GradientOverlay -> background (gradient)
        - ColorOverlay -> backgroundColor
        """
        if not layer.has_effects():
            return

        effects = layer.effects
        if not effects or not effects.items:
            return

        box_shadows: List[str] = []
        background_images: List[str] = []
        border_config: Dict[str, Any] = {}
        background_color: str = ""

        for effect in effects.items:
            # 跳过未启用的效果
            if hasattr(effect, "enabled") and not effect.enabled:
                continue
            if hasattr(effect, "shown") and not effect.shown:
                continue

            effect_name = effect.__class__.__name__

            # === DropShadow / InnerShadow -> boxShadow ===
            if effect_name in ("DropShadow", "InnerShadow"):
                self._parse_shadow_effect(effect, effect_name, box_shadows)

            # === Stroke -> border ===
            elif effect_name == "Stroke":
                self._parse_stroke_effect(effect, border_config, css)

            # === GradientOverlay -> background ===
            elif effect_name == "GradientOverlay":
                gradient_str = self._parse_gradient_overlay(effect)
                if gradient_str:
                    background_images.append(gradient_str)

            # === ColorOverlay -> backgroundColor ===
            elif effect_name == "ColorOverlay":
                color = _parse_psd_color_dict(
                    effect.color if hasattr(effect, "color") else {},
                    effect.opacity if hasattr(effect, "opacity") else 100.0,
                )
                if not background_color:
                    background_color = color

        # 合并到 css
        if box_shadows:
            css["boxShadow"] = box_shadows

        if background_images:
            if len(background_images) == 1:
                css["background"] = background_images[0]
            else:
                css["background"] = background_images

        if background_color:
            css["backgroundColor"] = background_color

    def _parse_shadow_effect(
        self, effect: Any, effect_name: str, box_shadows: List[str]
    ):
        """解析 DropShadow / InnerShadow 为 CSS boxShadow"""
        try:
            # 混合模式
            blend_mode = _parse_blend_mode(
                effect.blend_mode if hasattr(effect, "blend_mode") else b"Nrml"
            )

            # 颜色
            color_dict = effect.color if hasattr(effect, "color") else {}
            opacity = getattr(effect, "opacity", 100.0)
            color = _parse_psd_color_dict(color_dict, opacity)

            # 距离
            distance = getattr(effect, "distance", 0)

            # 角度 (PSD 使用 angle，范围 0-360)
            angle = getattr(effect, "angle", 90)
            if angle is None:
                angle = 90

            # 模糊半径
            size = getattr(effect, "size", 0)

            # 扩展 (choke)
            choke = getattr(effect, "choke", 0)

            # Photoshop 阴影偏移方向与 CSS 相反
            # angle=90 表示光源在左边，阴影向右
            import math

            angle_rad = math.radians(angle - 90)  # 转换为数学角度
            offset_x = round(distance * math.cos(angle_rad), 2)
            offset_y = round(distance * math.sin(angle_rad), 2)

            # CSS box-shadow: h-shadow v-shadow blur spread color
            spread = max(0, size - distance)  # 近似
            blur = size

            shadow = f"{offset_x}px {offset_y}px {blur}px {spread}px {color}"
            if blend_mode != "normal":
                shadow += f" / {blend_mode}"

            box_shadows.append(shadow)
        except (TypeError, ValueError, AttributeError) as e:
            print(f"  [警告] 解析阴影效果时出错: {e}")

    def _parse_stroke_effect(
        self, effect: Any, border_config: Dict[str, Any], css: Dict[str, Any]
    ):
        """解析 Stroke 为 CSS border"""
        try:
            # 描边宽度
            size = getattr(effect, "size", 1)

            # 描边位置: InsF=inside, OutF=outside, CtrF=center
            position = getattr(effect, "position", b"OutF")
            if isinstance(position, bytes):
                pos_str = position.decode("latin-1", errors="ignore")
            else:
                pos_str = str(position)

            # 填充类型: SClr=solid color, Grad=gradient
            fill_type = getattr(effect, "fill_type", b"SClr")
            if isinstance(fill_type, bytes):
                fill_str = fill_type.decode("latin-1", errors="ignore")
            else:
                fill_str = str(fill_type)

            # 混合模式
            blend_mode = _parse_blend_mode(
                effect.blend_mode if hasattr(effect, "blend_mode") else b"Nrml"
            )

            # 不透明度
            opacity = getattr(effect, "opacity", 100.0)

            if fill_str == "Grad":
                # 渐变描边 -> CSS border 使用图像
                gradient_data = effect.gradient if hasattr(effect, "gradient") else {}
                angle = getattr(effect, "angle", 0)
                gradient_str = _parse_gradient(gradient_data, angle)
                border_config["borderImage"] = gradient_str
            else:
                # 纯色描边
                color_dict = effect.color if hasattr(effect, "color") else {}
                color = _parse_psd_color_dict(color_dict, opacity)

            # CSS border
            if "borderImage" in border_config:
                css["border"] = f"{size}px solid transparent"
                css["borderImage"] = border_config["borderImage"]
            else:
                css["border"] = f"{size}px solid {color}"

            if blend_mode != "normal":
                css["borderBlendMode"] = blend_mode

        except (TypeError, ValueError, AttributeError) as e:
            print(f"  [警告] 解析描边效果时出错: {e}")

    def _parse_gradient_overlay(self, effect: Any) -> str:
        """解析 GradientOverlay 为 CSS background"""
        try:
            gradient_data = getattr(effect, "gradient", {})
            if not gradient_data:
                return ""

            angle = getattr(effect, "angle", 0)
            opacity = getattr(effect, "opacity", 100.0)

            gradient_str = _parse_gradient(gradient_data, angle)

            # 如果有透明度，应用到 background-color
            if opacity < 100:
                # 在 gradient 前面加一层透明色
                return f"rgba(0,0,0,{opacity/100}) {gradient_str.replace('linear-gradient', 'linear-gradient').split(',')[0]}, {gradient_str}"
            return gradient_str

        except (TypeError, ValueError, AttributeError) as e:
            print(f"  [警告] 解析渐变叠加效果时出错: {e}")
            return ""

    def _extract_mask_info(self, layer: Layer) -> Optional[Dict[str, Any]]:
        """
        提取图层遮罩信息

        支持两类遮罩：
        1. 剪贴蒙版 (Clipping Mask): 由 has_clip_layers() 检测
           - 该图层是剪贴组的"基底"，上层图层被其裁剪
           - CSS 可通过 overflow:hidden 或 clip-path 实现

        2. 图层蒙版 (Layer Mask): 由 has_mask() 检测
           - 灰度蒙版控制图层的透明度区域
           - CSS mask-image 支持导出蒙版图像

        Returns:
            遮罩信息字典或 None
        """
        mask_info: Dict[str, Any] = {}

        # === 1. 剪贴蒙版 (Clipping Mask) ===
        if layer.has_clip_layers():
            clips = layer.clip_layers
            clip_names = [clip.name for clip in clips if hasattr(clip, 'name')]
            mask_info["type"] = "clipping"
            mask_info["clipTargets"] = clip_names
            # 计算剪贴基底层的边界
            mask_info["clipBounds"] = {
                "x": layer.left,
                "y": layer.top,
                "w": layer.width,
                "h": layer.height,
            }

        # === 2. 图层蒙版 (Layer Mask) ===
        elif layer.has_mask():
            mask = layer.mask
            # 蒙版边界（相对于画布）
            if mask.bbox and len(mask.bbox) == 4:
                left, top, right, bottom = mask.bbox
                mask_info["type"] = "layer"
                mask_info["bbox"] = {
                    "x": left,
                    "y": top,
                    "w": right - left,
                    "h": bottom - top,
                }
                # 背景色（蒙版区域外的默认色）
                mask_info["backgroundColor"] = f"rgba(255,255,255,{mask.background_color / 255})" if mask.background_color else None
                mask_info["disabled"] = mask.disabled

                # 导出蒙版图像（可选，用于 CSS mask-image）
                try:
                    mask_img = mask.topil()
                    if mask_img:
                        mask_file_name = f"mask_{layer.layer_id}_{re.sub(r'[\\/*?:"<>|]', '', layer.name)}.png"
                        mask_path = os.path.join(self.assets_dir, mask_file_name)
                        mask_img.save(mask_path)
                        mask_info["maskImagePath"] = mask_path
                except Exception:
                    pass

        else:
            return None

        return mask_info if mask_info else None

    def _is_image_export_target(self, layer: Layer, layer_type: str) -> bool:
        """
        检测图层是否应该导出为图片

        Args:
            layer: PSD 图层对象
            layer_type: 图层类型

        Returns:
            是否应导出为图片
        """
        name_lower = layer.name.lower()
        # 检查是否包含图片标记
        for markers in LAYER_MARKERS.values():
            for marker in markers:
                if marker in name_lower:
                    return True
        # 智能对象默认导出
        if layer_type == "smartobject":
            return True
        return False

    def _infer_layout(self, children: List[Dict[str, Any]], group_rect: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """
        根据子图层位置信息推断 CSS flexbox 布局

        分析逻辑：
        - flexDirection: 比较子图层 X 方向和 Y 方向的离散程度
          Y 方向离散大 → column（列排布）
          X 方向离散大 → row（行排布）
        - alignItems: 根据子图层 Y 坐标的唯一值数量
          唯一值=1 → center（垂直居中对齐）
          唯一值>1 → flex-start（顶部对齐）
        - justifyContent: 根据子图层 X 坐标的唯一值数量
          唯一值=1 → center（水平居中对齐）
          唯一值>1 → flex-start（左侧对齐）
        - gap: 统计相邻子图层间的间距中位数
        - padding: 相对父组边界的留白

        Args:
            children: 子图层信息列表（已包含 rect）
            group_rect: 父组边界 {x, y, w, h}

        Returns:
            布局信息字典或 None
        """
        if not children:
            return None

        # 按 Y 第一、 X 第二排序（统一分析顺序）
        def sort_key(c):
            r = c.get("rect", {})
            return (r.get("y", 0), r.get("x", 0))

        sorted_children = sorted(children, key=sort_key)

        xs = [c["rect"]["x"] for c in sorted_children]
        ys = [c["rect"]["y"] for c in sorted_children]
        rights = [c["rect"]["x"] + c["rect"]["w"] for c in sorted_children]
        bottoms = [c["rect"]["y"] + c["rect"]["h"] for c in sorted_children]

        x_spread = max(xs) - min(xs) if xs else 0
        y_spread = max(ys) - min(ys) if ys else 0

        unique_xs = len(set(xs))
        unique_ys = len(set(ys))

        # --- flexDirection ---
        # Y 离散程度大于 X → 列布局；否则行布局
        if y_spread > x_spread * 1.2:
            flex_direction = "column"
        else:
            flex_direction = "row"

        # --- alignItems & justifyContent ---
        # alignItems 盯 Y 方向对齐（cross-axis）
        if unique_ys <= 1:
            align_items = "center"
        else:
            align_items = "stretch"

        # justifyContent 盯 X 方向对齐（main-axis）
        if unique_xs <= 1:
            justify_content = "center"
        else:
            justify_content = "flex-start"

        # --- gap（仅对多元素有意义）---
        gap: Optional[float] = None
        if len(sorted_children) >= 2:
            if flex_direction == "row":
                # 水平间距
                distances = []
                for i in range(1, len(sorted_children)):
                    dist = xs[i] - rights[i - 1]
                    if dist >= 0:
                        distances.append(dist)
                if distances:
                    gap = float(sorted(distances)[len(distances) // 2])
            else:
                # 垂直间距
                distances = []
                for i in range(1, len(sorted_children)):
                    dist = ys[i] - bottoms[i - 1]
                    if dist >= 0:
                        distances.append(dist)
                if distances:
                    gap = float(sorted(distances)[len(distances) // 2])

        # --- padding（相对父组边界）---
        padding_left = min(xs) - group_rect["x"] if xs else 0
        padding_top = min(ys) - group_rect["y"] if ys else 0
        padding_right = (group_rect["x"] + group_rect["w"]) - max(rights) if rights else 0
        padding_bottom = (group_rect["y"] + group_rect["h"]) - max(bottoms) if bottoms else 0

        # 全部为 0 或负数 → 说明子图层撑满组，忽略 padding
        has_padding = any(v > 0 for v in [padding_left, padding_top, padding_right, padding_bottom])

        layout: Dict[str, Any] = {
            "flexDirection": flex_direction,
            "alignItems": align_items,
            "justifyContent": justify_content,
        }

        if gap is not None and gap >= 0:
            layout["gap"] = round(gap, 1)

        if has_padding:
            # 标准化：只保留四个方向中大于 0 的
            pad = {}
            if padding_left > 0:
                pad["left"] = round(padding_left, 1)
            if padding_top > 0:
                pad["top"] = round(padding_top, 1)
            if padding_right > 0:
                pad["right"] = round(padding_right, 1)
            if padding_bottom > 0:
                pad["bottom"] = round(padding_bottom, 1)
            if pad:
                layout["padding"] = pad

        return layout

    def _parse_layers(
        self, layer_group: Any, parent_zindex: int = 0, depth: int = 0
    ) -> List[Dict[str, Any]]:
        """递归遍历图层树

        Args:
            layer_group: 图层组
            parent_zindex: 父层级 zIndex
            depth: 当前递归深度
        """
        # 超过最大深度，停止递归
        if depth >= self.MAX_RECURSION_DEPTH:
            print(f"  [警告] 达到最大递归深度 {self.MAX_RECURSION_DEPTH}，停止递归展开")
            return []

        layers = []
        local_zindex = parent_zindex

        for layer in layer_group:
            if not layer.visible:
                continue

            layer_type = self._get_layer_type(layer)
            name_lower = layer.name.lower()

            # 递增 zIndex
            local_zindex += 1
            current_zindex = local_zindex * 100 + parent_zindex

            # 检测组件语义类型
            component_type = _detect_component_type(name_lower, layer_type)

            # 检查是否标记为图片导出
            is_image_target = self._is_image_export_target(layer, layer_type)

            # 基础结构信息
            info: Dict[str, Any] = {
                "id": layer.layer_id,
                "name": layer.name,
                "type": layer_type,
                "componentType": component_type,
                "zIndex": current_zindex,
                "rect": {
                    "x": layer.left,
                    "y": layer.top,
                    "w": layer.width,
                    "h": layer.height,
                },
                "visible": layer.visible,
                "css": self._extract_css(layer),
            }

            # 提取遮罩信息
            mask_info = self._extract_mask_info(layer)
            if mask_info:
                info["mask"] = mask_info

            # 如果标记为图片，导出它并停止递归其子节点
            if is_image_target:
                path = self._export_image(layer)
                if path:
                    info["imagePath"] = path
                    info["type"] = "image"
                    if layer.is_group():
                        info["children"] = []
                    layers.append(info)
                    continue

            if info["type"] == "text":
                info["text"] = layer.text.strip() if layer.text else ""

            # 递归处理子图层
            if layer.is_group():
                info["children"] = self._parse_layers(layer, current_zindex, depth + 1)
                # 推理布局信息（仅对有 2+ 个可见子图层的组生效）
                if len(info["children"]) >= 2:
                    layout = self._infer_layout(info["children"], info["rect"])
                    if layout:
                        info["layout"] = layout
            else:
                info["children"] = []

            layers.append(info)

        return layers

    def get_data(self) -> Dict[str, Any]:
        """获取整个文档的结构数据"""
        return {
            "meta": {
                "canvas": {"w": self.psd.width, "h": self.psd.height},
                "exportedAt": self.psd.creation_time if hasattr(self.psd, "creation_time") else None,
                "version": "1.0",
            },
            "designTokens": self._tokens_collector.to_dict(),
            "layers": self._parse_layers(self.psd),
        }

    def save_json(self, output_filepath: str):
        """将解析后的数据保存为 JSON 文件"""
        data = self.get_data()

        # 提取目录路径，确保输出目录存在
        dir_path = os.path.dirname(os.path.abspath(output_filepath))
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"[+] 解析成功！JSON 已保存至: {output_filepath}")
        print(f"[+] 资源文件已导出至: {self.assets_dir}")


def main():
    # 设置命令行参数解析
    parser = argparse.ArgumentParser(description="PSD 转换为 UI JSON 工具")
    parser.add_argument("-i", "--input", required=True, help="PSD 文件的绝对路径")
    parser.add_argument(
        "-oa",
        "--output-assets",
        default="assets",
        help="切图资源的生成目录 (默认为 assets)",
    )
    # 新增：允许指定 JSON 输出文件路径
    parser.add_argument(
        "-oj",
        "--output-json",
        help="输出的 JSON 文件路径 (默认在当前目录生成: 文件名_structure.json)",
    )

    args = parser.parse_args()

    # 处理 JSON 输出路径逻辑
    if args.output_json:
        json_path = os.path.abspath(args.output_json)
    else:
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        json_path = os.path.join(os.getcwd(), f"{base_name}_structure.json")

    try:
        # 执行解析过程
        psd_parser = PSDParser(args.input, args.output_assets)
        psd_parser.save_json(json_path)
    except Exception as e:
        print(f"[!] 发生致命错误: {str(e)}")


if __name__ == "__main__":
    main()
