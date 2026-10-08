"""
KeynoteManager — 读取和遍历 Apple Keynote .key 文件中的文字和图片。

依赖: keynote-parser (pip install keynote-parser)
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from PIL import Image

from keynote_parser.codec import IWAFile
from keynote_parser.file_utils import file_reader


class KeynoteManager:
    """解析 .key 文件，提供按幻灯片遍历文字和图片的能力。"""

    def __init__(self, key_path: str):
        self.key_path = str(key_path)

        # 原始数据
        self._iwa_data: Dict[str, dict] = {}       # "Index/Slide-1.iwa" -> dict
        self._data_files: Dict[str, bytes] = {}     # "Data/xxx" -> raw bytes

        # id -> 对象信息索引
        self._id_index: Dict[int, dict] = {}

        # 幻灯片 id 列表（按文件排序）
        self._slide_ids: List[int] = []

        # 脏追踪（用于 save 时判断哪些文件需要重新序列化）
        self._dirty_iwa_files: set = set()
        self._dirty_data_files: set = set()

        self._load()

    # ── 内部方法 ──────────────────────────────────────────────

    def _load(self):
        """读取 .key 文件中的所有数据并建立索引。"""
        for filename, handle in file_reader(self.key_path):
            raw = handle.read()
            if ".iwa" in filename:
                try:
                    iwa = IWAFile.from_buffer(raw, filename)
                    self._iwa_data[filename] = iwa.to_dict()
                except (ValueError, NotImplementedError) as e:
                    print(f"跳过无法解析的文件 {filename}: {e}")
                    continue
            elif filename.startswith("Data/"):
                self._data_files[filename] = raw

        self._build_index()
        self._find_slides()

    def _build_index(self):
        """将每个 archive header 中的 identifier 与其 objects 建立映射。"""
        for fname, content in self._iwa_data.items():
            for ci, chunk in enumerate(content.get("chunks", [])):
                for ai, archive in enumerate(chunk.get("archives", [])):
                    header = archive.get("header", {})
                    objects = archive.get("objects", [])
                    identifier = header.get("identifier")
                    if identifier is not None and objects:
                        self._id_index[identifier] = {
                            "filename": fname,
                            "chunk_idx": ci,
                            "archive_idx": ai,
                            "header": header,
                            "objects": objects,
                        }

    def _find_slides(self):
        """找出真实幻灯片（非模板），尽量保留文档顺序。"""
        slide_archives: dict[int, dict] = {}
        for obj_id, info in self._id_index.items():
            first_obj = info["objects"][0]
            if first_obj.get("_pbtype") == "KN.SlideArchive":
                slide_archives[obj_id] = info

        # 优先尝试从 ShowArchive.slideTree 读取文档顺序
        for info in self._id_index.values():
            first_obj = info["objects"][0]
            if first_obj.get("_pbtype") == "KN.ShowArchive":
                slide_tree = first_obj.get("slideTree", {})
                tree_slides = slide_tree.get("slides", [])
                if tree_slides:
                    ordered = []
                    for node_ref in tree_slides:
                        node_id = node_ref.get("identifier")
                        node_info = self._id_index.get(node_id)
                        if node_info:
                            slide_ref = node_info["objects"][0].get("slide", {})
                            slide_id = slide_ref.get("identifier")
                            if slide_id and slide_id in slide_archives:
                                ordered.append(slide_id)
                    if ordered:
                        self._slide_ids = ordered
                        return
                break

        # 回退：仅保留非模板幻灯片
        self._slide_ids = sorted(
            sid for sid, info in slide_archives.items()
            if "templateSlide" in info["objects"][0]
        )

    def _resolve(self, ref: Optional[dict]) -> Optional[dict]:
        """根据 TSP.Reference dict 查找对应的对象信息。"""
        if ref is None:
            return None
        obj_id = ref.get("identifier")
        if obj_id is None:
            return None
        return self._id_index.get(obj_id)

    @staticmethod
    def _get_text_from_storage(storage_obj: dict) -> str:
        """从 TSWP.StorageArchive 对象中提取纯文本。

        注意: text 字段可能是字符串或字符串列表。
        """
        text = storage_obj.get("text", "")
        if isinstance(text, list):
            return "\n".join(text)
        return text

    def _get_drawable_text(self, drawable_info: dict, slide_obj: dict = None) -> str:
        """从 drawable 对象中提取文字。

        支持:
          - TSWP.ShapeInfoArchive / TSD.ShapeArchive (storage 在顶层)
          - KN.PlaceholderArchive (storage 在 super 层级)

        如果 storage 中无文字且提供了 slide_obj，尝试从模板幻灯片继承。
        """
        obj = drawable_info["objects"][0]
        pbtype = obj.get("_pbtype", "")

        if pbtype == "KN.PlaceholderArchive":
            super_obj = obj.get("super", {})
            storage_ref = super_obj.get("deprecatedStorage", {}) or super_obj.get("ownedStorage", {})
        else:
            storage_ref = obj.get("deprecatedStorage", {}) or obj.get("ownedStorage", {})

        storage_info = self._resolve(storage_ref)
        if storage_info:
            text = self._get_text_from_storage(storage_info["objects"][0])
            if text:
                return text

        # 回退：从模板幻灯片继承文字
        if slide_obj and pbtype == "KN.PlaceholderArchive":
            kind = obj.get("kind", "")
            template_ref = slide_obj.get("templateSlide", {})
            template_info = self._resolve(template_ref)
            if template_info:
                template_slide = template_info["objects"][0]
                if "Title" in kind:
                    inherit_ref = template_slide.get("titlePlaceholder", {})
                elif "Body" in kind:
                    inherit_ref = template_slide.get("bodyPlaceholder", {})
                else:
                    inherit_ref = {}
                if inherit_ref:
                    inherit_info = self._resolve(inherit_ref)
                    if inherit_info:
                        inherit_obj = inherit_info["objects"][0]
                        s = inherit_obj.get("super", {})
                        sr = s.get("deprecatedStorage", {}) or s.get("ownedStorage", {})
                        si = self._resolve(sr)
                        if si:
                            return self._get_text_from_storage(si["objects"][0])

        return ""

    @staticmethod
    def _get_drawable_geometry(drawable_info: dict) -> dict:
        """获取 drawable 的位置和尺寸信息。"""
        obj = drawable_info["objects"][0]
        pbtype = obj.get("_pbtype", "")

        if pbtype == "TSD.ImageArchive":
            super_field = obj.get("super", {})
            return super_field.get("geometry", {})

        if pbtype == "KN.PlaceholderArchive":
            # PlaceholderArchive.super.super.super.geometry
            super_level1 = obj.get("super", {})
            super_level2 = super_level1.get("super", {})
            return super_level2.get("geometry", {})

        if pbtype in ("TSWP.ShapeInfoArchive", "TSD.ShapeArchive"):
            super_field = obj.get("super", {})
            if pbtype == "TSWP.ShapeInfoArchive":
                shape_super = super_field.get("super", {})
                return shape_super.get("geometry", {})
            return super_field.get("geometry", {})

        return {}

    # ── 公开属性 ──────────────────────────────────────────────

    @property
    def slide_count(self) -> int:
        """幻灯片总数。"""
        return len(self._slide_ids)

    @property
    def slides(self) -> List[dict]:
        """返回所有幻灯片对象信息的列表（每项含 id、原始对象）。"""
        result = []
        for sid in self._slide_ids:
            info = self._id_index[sid]
            result.append({
                "id": sid,
                "object": info["objects"][0],
                "info": info,
            })
        return result

    # ── 遍历文字 ──────────────────────────────────────────────

    def iter_slide_texts(self, slide_id: int) -> Iterator[dict]:
        """遍历指定幻灯片的全部文字元素。

        每个 yield 包含:
            - type: "title" | "body" | "shape" | "textbox"
            - text: 文本内容
            - geometry: {x, y, width, height}（可能为空）
        """
        info = self._id_index.get(slide_id)
        if not info:
            return
        slide_obj = info["objects"][0]

        # 记录已处理的占位符 identifier，避免后续重复
        seen_placeholder_ids: set = set()

        # 标题占位符
        title_ref = slide_obj.get("titlePlaceholder")
        title_info = self._resolve(title_ref)
        if title_info:
            text = self._get_drawable_text(title_info, slide_obj)
            seen_placeholder_ids.add(title_ref.get("identifier"))
            yield {"type": "title", "text": text, "geometry": {}}

        # 正文占位符
        body_ref = slide_obj.get("bodyPlaceholder")
        body_info = self._resolve(body_ref)
        if body_info:
            text = self._get_drawable_text(body_info, slide_obj)
            seen_placeholder_ids.add(body_ref.get("identifier"))
            yield {"type": "body", "text": text, "geometry": {}}

        # 其他 drawable 对象（由 ownedDrawables 引用，可能也有 drawablesZOrder）
        drawable_refs = (
            slide_obj.get("ownedDrawables", [])
            or slide_obj.get("drawablesZOrder", [])
        )
        for ref in drawable_refs:
            # 跳过已在标题/正文占位符中处理过的
            if ref.get("identifier") in seen_placeholder_ids:
                continue
            drawable_info = self._resolve(ref)
            if not drawable_info:
                continue

            dobj = drawable_info["objects"][0]
            pbtype = dobj.get("_pbtype", "")

            if pbtype in ("TSWP.ShapeInfoArchive", "TSD.ShapeArchive", "KN.PlaceholderArchive"):
                text = self._get_drawable_text(drawable_info, slide_obj)
                geo = self._get_drawable_geometry(drawable_info)
                if pbtype == "KN.PlaceholderArchive":
                    kind = dobj.get("kind", "")
                    if "Body" in kind:
                        etype = "body"
                    elif "Title" in kind:
                        etype = "title"
                    else:
                        etype = "placeholder"
                else:
                    etype = "textbox" if pbtype == "TSWP.ShapeInfoArchive" else "shape"
                yield {"type": etype, "text": text, "geometry": geo}

    def get_slide_texts(self, slide_id: int) -> List[dict]:
        """获取指定幻灯片的所有文字信息列表。"""
        return list(self.iter_slide_texts(slide_id))

    def extract_all_text(self) -> list:
        """提取所有幻灯片的全部文字。"""
        parts = []
        for slide_id in self._slide_ids:
            for slide_item in self.iter_slide_texts(slide_id):
                t = slide_item["text"].strip()
                if t:
                    parts.append(t)
        return parts

    # ── 遍历图片 ──────────────────────────────────────────────

    def iter_slide_images(self, slide_id: int) -> Iterator[dict]:
        """遍历指定幻灯片的全部图片。

        每个 yield 包含:
            - identifier: 图片对象的数字 ID
            - data_id: 对应 Data/ 目录中文件的 ID
            - filename: Data/ 中的文件名（可能为空）
            - raw_bytes: 原始二进制数据
            - geometry: {x, y, width, height}（可能为空）
        """
        info = self._id_index.get(slide_id)
        if not info:
            return
        slide_obj = info["objects"][0]

        drawable_refs = (
            slide_obj.get("ownedDrawables", [])
            or slide_obj.get("drawablesZOrder", [])
        )
        for ref in drawable_refs:
            drawable_info = self._resolve(ref)
            if not drawable_info:
                continue

            obj = drawable_info["objects"][0]
            pbtype = obj.get("_pbtype", "")
            if pbtype != "TSD.ImageArchive":
                continue

            data_ref = obj.get("data") or obj.get("database_data") or {}
            data_id = data_ref.get("identifier")

            geo = self._get_drawable_geometry(drawable_info)

            # 找出 Data/ 中对应的文件
            matched_filename = ""
            matched_bytes = b""
            if data_id is not None:
                for fname, raw in self._data_files.items():
                    if str(data_id) in fname:
                        matched_filename = fname
                        matched_bytes = raw
                        break
                # 如果没精确匹配到文件名，尝试通过 identifier 查找
                if not matched_bytes:
                    # 部分 Keynote 的文件名就是 Data/{identifier}
                    candidate = f"Data/{data_id}"
                    if candidate in self._data_files:
                        matched_filename = candidate
                        matched_bytes = self._data_files[candidate]

            yield {
                "identifier": drawable_info["header"].get("identifier"),
                "data_id": data_id,
                "filename": matched_filename,
                "raw_bytes": matched_bytes,
                "geometry": geo,
            }

    def get_slide_images(self, slide_id: int) -> List[dict]:
        """获取指定幻灯片的所有图片信息列表。"""
        return list(self.iter_slide_images(slide_id))

    @staticmethod
    def save_image(image_info: dict, output_dir: str) -> Optional[str]:
        """将图片保存到本地磁盘。

        Args:
            image_info: iter_slide_images 返回的字典。
            output_dir: 输出目录。

        Returns:
            保存后的文件路径，失败返回 None。
        """
        raw = image_info.get("raw_bytes")
        if not raw:
            return None

        os.makedirs(output_dir, exist_ok=True)

        # 尝试保留原始文件名
        fname = image_info.get("filename", "")
        if fname:
            base = os.path.basename(fname)
        else:
            base = f"image_{image_info['data_id']}.bin"

        out_path = os.path.join(output_dir, base)

        # 尝试以图片格式保存（根据实际数据确定扩展名）
        try:
            img = Image.open(BytesIO(raw))
            # 修正扩展名
            ext = img.format.lower() if img.format else "bin"
            base_no_ext = os.path.splitext(base)[0]
            out_path = os.path.join(output_dir, f"{base_no_ext}.{ext}")
            img.save(out_path)
        except Exception:
            # 无法识别为图片，原样保存
            with open(out_path, "wb") as f:
                f.write(raw)

        return out_path

    def save_all_images(self, output_dir: str) -> List[str]:
        """保存所有幻灯片中的所有图片。

        Returns:
            已保存的文件路径列表。
        """
        saved = []
        for sid in self._slide_ids:
            for img_info in self.iter_slide_images(sid):
                path = self.save_image(img_info, output_dir)
                if path:
                    saved.append(path)
        return saved

    # ── 文字替换 ──────────────────────────────────────────────

    def _replace_text_in_drawable(
        self, ref: Optional[dict], old_text: str, new_text: str
    ) -> bool:
        """尝试替换一个 drawable 对象中的文字。"""
        drawable_info = self._resolve(ref)
        if not drawable_info:
            return False

        obj = drawable_info["objects"][0]
        pbtype = obj.get("_pbtype", "")
        if pbtype not in ("TSWP.ShapeInfoArchive", "TSD.ShapeArchive", "KN.PlaceholderArchive"):
            return False

        # 找到 storage（文本存储）
        if pbtype == "KN.PlaceholderArchive":
            super_obj = obj.get("super", {})
            storage_ref = super_obj.get("deprecatedStorage", {}) or super_obj.get("ownedStorage", {})
        else:
            storage_ref = obj.get("deprecatedStorage", {}) or obj.get("ownedStorage", {})
        storage_info = self._resolve(storage_ref)
        if not storage_info:
            return False

        storage_obj = storage_info["objects"][0]
        text = storage_obj.get("text", "")
        if isinstance(text, list):
            joined = "\n".join(text)
            if old_text not in joined:
                return False
            storage_obj["text"] = [t.replace(old_text, new_text) for t in text]
        else:
            if old_text not in text:
                return False
            storage_obj["text"] = text.replace(old_text, new_text)
        self._dirty_iwa_files.add(storage_info["filename"])
        self._dirty_iwa_files.add(drawable_info["filename"])
        return True

    def replace_text(self, slide_id: int, old_text: str, new_text: str) -> int:
        """替换指定幻灯片中的文字。

        Args:
            slide_id: 幻灯片 id（对应 slides 返回的 id）。
            old_text: 要替换的文字。
            new_text: 替换后的文字。

        Returns:
            被修改的 drawable 数量。
        """
        info = self._id_index.get(slide_id)
        if not info:
            return 0
        slide_obj = info["objects"][0]
        count = 0

        # 标题占位符
        if self._replace_text_in_drawable(
            slide_obj.get("titlePlaceholder"), old_text, new_text
        ):
            count += 1

        # 正文占位符
        if self._replace_text_in_drawable(
            slide_obj.get("bodyPlaceholder"), old_text, new_text
        ):
            count += 1

        # 其他 drawable
        drawable_refs = (
            slide_obj.get("ownedDrawables", [])
            or slide_obj.get("drawablesZOrder", [])
        )
        for ref in drawable_refs:
            if self._replace_text_in_drawable(ref, old_text, new_text):
                count += 1

        return count

    def replace_all_text(self, old_text: str, new_text: str) -> int:
        """替换所有幻灯片中的文字。

        Returns:
            被修改的 drawable 数量。
        """
        total = 0
        for sid in self._slide_ids:
            total += self.replace_text(sid, old_text, new_text)
        return total

    # ── 图片替换 ──────────────────────────────────────────────

    def replace_image(
        self, slide_id: int, image_identifier: int, image_path: str
    ) -> bool:
        """替换指定幻灯片中的图片。

        Args:
            slide_id: 幻灯片 id。
            image_identifier: 图片对象的 identifier（来自 iter_slide_images）。
            image_path: 新图片的文件路径。

        Returns:
            是否成功替换。
        """
        for img_info in self.iter_slide_images(slide_id):
            if img_info.get("identifier") == image_identifier:
                data_id = img_info.get("data_id")
                if data_id is None:
                    return False
                # 找到对应的 Data/ 文件并替换二进制数据
                for fname in list(self._data_files.keys()):
                    if str(data_id) in fname:
                        with open(image_path, "rb") as f:
                            self._data_files[fname] = f.read()
                        self._dirty_data_files.add(fname)
                        return True
                # 尝试直接构造 Data/{data_id} 文件名
                candidate = f"Data/{data_id}"
                if candidate in self._data_files:
                    with open(image_path, "rb") as f:
                        self._data_files[candidate] = f.read()
                    self._dirty_data_files.add(candidate)
                    return True
        return False

    def replace_all_images(self, image_path: str) -> int:
        """替换所有幻灯片中的所有图片。

        Returns:
            被替换的图片数量。
        """
        count = 0
        for sid in self._slide_ids:
            for img_info in self.iter_slide_images(sid):
                if self.replace_image(sid, img_info.get("identifier"), image_path):
                    count += 1
        return count

    # ── 保存 ──────────────────────────────────────────────────

    def save(self, output_path: Optional[str] = None) -> str:
        """保存修改后的 .key 文件。

        Args:
            output_path: 输出路径。为 None 则覆盖原文件。

        Returns:
            保存的文件路径。
        """
        import zipfile

        save_path = output_path or self.key_path

        # 重新序列化被修改的 IWA 文件
        updated_iwa: Dict[str, bytes] = {}
        for fname in self._dirty_iwa_files:
            if fname in self._iwa_data:
                iwa = IWAFile.from_dict(self._iwa_data[fname])
                updated_iwa[fname] = iwa.to_buffer()

        # 重新打包 zip
        with zipfile.ZipFile(self.key_path, "r") as zin:
            with zipfile.ZipFile(save_path, "w") as zout:
                for item in zin.infolist():
                    raw = zin.read(item.filename)
                    # IWA 文件 — 使用重新序列化的数据
                    if item.filename in updated_iwa:
                        zout.writestr(item, updated_iwa[item.filename])
                    # Data/ 文件 — 如果被修改则使用新数据
                    elif item.filename in self._dirty_data_files:
                        zout.writestr(item, self._data_files[item.filename])
                    else:
                        zout.writestr(item, raw)

        self._dirty_iwa_files.clear()
        self._dirty_data_files.clear()
        return save_path

    # ── 汇总信息 ──────────────────────────────────────────────

    def summary(self) -> dict:
        """返回整个文档的结构摘要。"""
        result = {
            "file": self.key_path,
            "slide_count": self.slide_count,
            "slides": [],
        }
        for sid in self._slide_ids:
            slide_summary = {"id": sid, "texts": [], "images": []}
            for t in self.iter_slide_texts(sid):
                if t["text"].strip():
                    slide_summary["texts"].append({
                        "type": t["type"],
                        "preview": t["text"].strip()[:60],
                    })
            for img in self.iter_slide_images(sid):
                slide_summary["images"].append({
                    "data_id": img["data_id"],
                    "filename": img["filename"],
                    "has_bytes": bool(img["raw_bytes"]),
                })
            result["slides"].append(slide_summary)
        return result


# ── 使用示例 ──────────────────────────────────────────────────

if __name__ == "__main__":
    path = Path(__file__).parent / "sample.key"
    if not path.exists():
        raise Exception(f"no file {path.as_posix()}")
    mgr = KeynoteManager(path.as_posix())

    ems = mgr.extract_all_text()
    print(ems)

    print(f"幻灯片数量: {mgr.slide_count}")
    print()

    for slide in mgr.slides:
        sid = slide["id"]
        print(f"{'='*60}")
        print(f"幻灯片 {sid}")
        for item in mgr.iter_slide_texts(sid):
            if item["text"].strip():
                print(f"  [{item['type']}] {item['text'].strip()[:100]}")
        for img in mgr.iter_slide_images(sid):
            print(f"  [图片] data_id={img['data_id']}")

    print(f"\n{'='*60}")
    print("所有文字内容:")
    print(mgr.extract_all_text())

    old_text = "{name}"

    new_text = "123"

    count = mgr.replace_all_text(old_text, new_text)
    print(f"已替换 {count} 处文字: {old_text!r} -> {new_text!r}")
