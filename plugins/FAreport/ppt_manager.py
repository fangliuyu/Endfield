"""
PPTManager — 读取和遍历 PowerPoint .pptx 文件中的文字和图片。

依赖: python-pptx (pip install python-pptx)
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Iterator, List, Optional

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.picture import Picture
from pptx.util import Emu


class PPTManager:
    """解析 .pptx 文件，提供按幻灯片遍历文字和图片的能力。"""

    def __init__(self, pptx_path: str):
        self.pptx_path = str(pptx_path)
        self._prs = Presentation(pptx_path)

    # ── 公开属性 ──────────────────────────────────────────────

    @property
    def slide_count(self) -> int:
        """幻灯片总数。"""
        return len(self._prs.slides)

    @property
    def slide_size(self) -> dict:
        """幻灯片尺寸（EMU 单位）。"""
        return {
            "width": self._prs.slide_width,
            "height": self._prs.slide_height,
        }

    @property
    def slides(self) -> List[dict]:
        """返回所有幻灯片的信息列表。"""
        result = []
        for i, slide in enumerate(self._prs.slides):
            layout_name = slide.slide_layout.name if slide.slide_layout else ""
            result.append({
                "index": i,
                "slide": slide,
                "layout": layout_name,
            })
        return result

    # ── 辅助方法 ──────────────────────────────────────────────

    @staticmethod
    def _emu_to_pt(emu: int) -> float:
        """EMU 单位转换为磅（pt）。"""
        return Emu(emu).pt if emu is not None else 0.0

    @staticmethod
    def _geometry_from_shape(shape) -> dict:
        """获取形状的位置和尺寸（单位: 磅）。"""
        return {
            "x": round(PPTManager._emu_to_pt(shape.left), 1),
            "y": round(PPTManager._emu_to_pt(shape.top), 1),
            "width": round(PPTManager._emu_to_pt(shape.width), 1),
            "height": round(PPTManager._emu_to_pt(shape.height), 1),
        }

    # ── 遍历文字 ──────────────────────────────────────────────

    @staticmethod
    def _extract_text_from_shape(shape) -> str:
        """从形状中提取纯文本（包括段落内所有 run 的文本）。"""
        if not shape.has_text_frame:
            return ""
        parts = []
        for paragraph in shape.text_frame.paragraphs:
            text = paragraph.text.strip()
            if text:
                parts.append(text)
        return "\n".join(parts)

    def iter_slide_texts(self, slide_index: int) -> Iterator[dict]:
        """遍历指定幻灯片的全部文字元素。

        每个 yield 包含:
            - type: "title" | "body" | "shape" | "textbox" | "table" | "group"
            - text: 文本内容
            - geometry: {x, y, width, height}
            - shape_name: PowerPoint 中形状的名称
        """
        if slide_index < 0 or slide_index >= self.slide_count:
            return

        slide = self._prs.slides[slide_index]

        # 通过占位符索引判断标题和正文
        for shape in slide.shapes:
            geom = self._geometry_from_shape(shape)
            info = {
                "shape_name": shape.name,
                "geometry": geom,
            }

            stype = shape.shape_type

            # 表格
            if stype == MSO_SHAPE_TYPE.TABLE:
                table = shape.table
                rows_text = []
                for row in table.rows:
                    cells_text = [cell.text.strip() for cell in row.cells]
                    rows_text.append("\t".join(cells_text))
                info.update({"type": "table", "text": "\n".join(rows_text)})
                yield info
                continue

            # 组合形状 — 递归提取
            if stype == MSO_SHAPE_TYPE.GROUP:
                group_texts = []
                for child in shape.shapes:
                    t = self._extract_text_from_shape(child)
                    if t.strip():
                        group_texts.append(t)
                info.update({"type": "group", "text": "\n".join(group_texts)})
                yield info
                continue

            # 普通文本框
            text = self._extract_text_from_shape(shape)
            if not text.strip():
                continue

            # 判断是否为占位符（标题/正文）
            if shape.is_placeholder:
                ph = shape.placeholder_format
                if ph.idx == 0:
                    info["type"] = "title"
                else:
                    info["type"] = "body"
            else:
                info["type"] = "textbox"

            info["text"] = text
            yield info

    def get_slide_texts(self, slide_index: int) -> List[dict]:
        """获取指定幻灯片的所有文字信息列表。"""
        return list(self.iter_slide_texts(slide_index))

    def extract_all_text(self) -> list:
        """提取所有幻灯片的全部文字，用 sep 连接。"""
        parts = []
        for i in range(self.slide_count):
            for slide_item in self.iter_slide_texts(i):
                t = slide_item["text"].strip()
                if t:
                    parts.append(t)
        return parts

    # ── 遍历图片 ──────────────────────────────────────────────

    def iter_slide_images(self, slide_index: int) -> Iterator[dict]:
        """遍历指定幻灯片的全部图片。

        每个 yield 包含:
            - shape_name: PowerPoint 中的形状名称
            - image: pptx.shapes.picture.Picture 对象
            - content_type: 图片 MIME 类型
            - blob: 图片二进制数据
            - ext: 推测的文件扩展名
            - geometry: {x, y, width, height}
        """
        if slide_index < 0 or slide_index >= self.slide_count:
            return

        slide = self._prs.slides[slide_index]
        for shape in slide.shapes:
            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue

            pic: Picture = shape.image
            yield {
                "shape_name": shape.name,
                "image": pic,
                "content_type": pic.image.content_type,
                "blob": pic.image.blob,
                "ext": self._guess_ext(pic.image.content_type),
                "geometry": self._geometry_from_shape(shape),
            }

    def get_slide_images(self, slide_index: int) -> List[dict]:
        """获取指定幻灯片的所有图片信息列表。"""
        return list(self.iter_slide_images(slide_index))

    @staticmethod
    def _guess_ext(content_type: str) -> str:
        """根据 MIME 类型推测文件扩展名。"""
        mapping = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/gif": "gif",
            "image/bmp": "bmp",
            "image/tiff": "tiff",
            "image/webp": "webp",
            "image/svg+xml": "svg",
        }
        return mapping.get(content_type, "bin")

    @staticmethod
    def save_image(image_info: dict, output_dir: str) -> Optional[str]:
        """将图片保存到本地磁盘。

        Args:
            image_info: iter_slide_images 返回的字典。
            output_dir: 输出目录。

        Returns:
            保存后的文件路径，失败返回 None。
        """
        blob = image_info.get("blob")
        if not blob:
            return None

        os.makedirs(output_dir, exist_ok=True)

        ext = image_info.get("ext", "bin")
        name = image_info.get("shape_name", "image")
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)

        # 先保持 PIL 能识别的扩展名
        out_path = os.path.join(output_dir, f"{safe_name}.{ext}")
        try:
            img = Image.open(BytesIO(blob))
            img.save(out_path)
        except Exception:
            with open(out_path, "wb") as f:
                f.write(blob)

        return out_path

    def save_all_images(self, output_dir: str) -> List[str]:
        """保存所有幻灯片中的所有图片。

        Returns:
            已保存的文件路径列表。
        """
        saved = []
        for i in range(self.slide_count):
            for img_info in self.iter_slide_images(i):
                path = self.save_image(img_info, output_dir)
                if path:
                    saved.append(path)
        return saved

    # ── 文字替换 ──────────────────────────────────────────────

    @staticmethod
    def _replace_text_in_shape(shape, old_text: str, new_text: str) -> int:
        """替换形状中的文字。返回替换次数。"""
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        count = 0

        # 表格
        if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
            table = shape.table
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.text_frame.paragraphs:
                        for run in paragraph.runs:
                            if old_text in run.text:
                                run.text = run.text.replace(old_text, new_text)
                                count += 1
            return count

        # 普通文本框
        if not shape.has_text_frame:
            return 0
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                if old_text in run.text:
                    run.text = run.text.replace(old_text, new_text)
                    count += 1
        return count

    def replace_text(self, slide_index: int, old_text: str, new_text: str) -> int:
        """替换指定幻灯片中的文字（精确匹配）。

        Args:
            slide_index: 幻灯片索引（0-based）。
            old_text: 要替换的文字。
            new_text: 替换后的文字。

        Returns:
            被修改的形状数量。
        """
        if slide_index < 0 or slide_index >= self.slide_count:
            return 0
        slide = self._prs.slides[slide_index]
        count = 0
        for shape in slide.shapes:
            count += self._replace_text_in_shape(shape, old_text, new_text)
        return count

    def replace_all_text(self, old_text: str, new_text: str) -> int:
        """替换所有幻灯片中的文字。

        Returns:
            被修改的形状数量。
        """
        total = 0
        for i in range(self.slide_count):
            total += self.replace_text(i, old_text, new_text)
        return total

    # ── 图片替换 ──────────────────────────────────────────────

    @staticmethod
    def _replace_image_in_shape(shape, image_path: str) -> bool:
        """替换形状中的图片。"""
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            return False

        blip = shape.element.find(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
        )
        if blip is None:
            return False

        r_id = blip.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
        )
        if r_id is None:
            return False

        part = shape.part.related_part(r_id)
        with open(image_path, "rb") as f:
            part._blob = f.read()
        return True

    def replace_image(self, slide_index: int, shape_name: str, image_path: str) -> bool:
        """替换指定幻灯片中特定形状的图片。

        Args:
            slide_index: 幻灯片索引（0-based）。
            shape_name: 形状的名称（对应 iter_slide_images 中的 shape_name）。
            image_path: 新图片的文件路径。

        Returns:
            是否成功替换。
        """
        if slide_index < 0 or slide_index >= self.slide_count:
            return False
        slide = self._prs.slides[slide_index]
        for shape in slide.shapes:
            if shape.name == shape_name:
                if self._replace_image_in_shape(shape, image_path):
                    return True
        return False

    def replace_all_images(self, image_path: str) -> int:
        """替换所有幻灯片中的所有图片。

        Returns:
            被替换的图片数量。
        """
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        count = 0
        for i in range(self.slide_count):
            slide = self._prs.slides[i]
            for shape in slide.shapes:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    if self._replace_image_in_shape(shape, image_path):
                        count += 1
        return count

    # ── 保存 ──────────────────────────────────────────────────

    def save(self, output_path: Optional[str] = None) -> str:
        """保存修改后的 .pptx 文件。

        Args:
            output_path: 输出路径。为 None 则覆盖原文件。

        Returns:
            保存的文件路径。
        """
        path = output_path or self.pptx_path
        self._prs.save(path)
        return path

    # ── 汇总信息 ──────────────────────────────────────────────

    def summary(self) -> dict:
        """返回整个文档的结构摘要。"""
        result = {
            "file": self.pptx_path,
            "slide_count": self.slide_count,
            "slide_size": self.slide_size,
            "slides": [],
        }
        for i in range(self.slide_count):
            slide_summary = {"index": i, "texts": [], "images": []}
            for item in self.iter_slide_texts(i):
                if item["text"].strip():
                    slide_summary["texts"].append({
                        "type": item["type"],
                        "preview": item["text"].strip()[:60],
                    })
            for img in self.iter_slide_images(i):
                slide_summary["images"].append({
                    "shape_name": img["shape_name"],
                    "content_type": img["content_type"],
                })
            result["slides"].append(slide_summary)
        return result


# ── 使用示例 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python ppt_manager.py <path_to.pptx> [commands..]")
        print("  无命令: 遍历展示文字和图片")
        print("  replace <旧文字> <新文字>: 替换所有幻灯片中的文字")
        print("  replace-img <图片路径>: 替换所有图片")
        sys.exit(1)

    path = sys.argv[1]
    mgr = PPTManager(path)

    if len(sys.argv) >= 4 and sys.argv[2] == "replace":
        old_text, new_text = sys.argv[3], sys.argv[4]
        count = mgr.replace_all_text(old_text, new_text)
        mgr.save()
        print(f"已替换 {count} 处文字: {old_text!r} -> {new_text!r}")
        print(f"已保存到 {path}")

    elif len(sys.argv) >= 4 and sys.argv[2] == "replace-img":
        img_path = sys.argv[3]
        count = mgr.replace_all_images(img_path)
        mgr.save()
        print(f"已替换 {count} 张图片 -> {img_path}")
        print(f"已保存到 {path}")

    else:
        print(f"幻灯片数量: {mgr.slide_count}")
        print(f"幻灯片尺寸: {mgr.slide_size}")
        print()

        for slide in mgr.slides:
            idx = slide["index"]
            print(f"{'='*60}")
            print(f"幻灯片 {idx + 1} (布局: {slide['layout']})")
            for item in mgr.iter_slide_texts(idx):
                if item["text"].strip():
                    print(f"  [{item['type']}] {item['text'].strip()[:100]}")
            for img in mgr.iter_slide_images(idx):
                print(f"  [图片] {img['shape_name']} ({img['content_type']})")

        print(f"\n{'='*60}")
        print("所有文字内容:")
        print(mgr.extract_all_text())
