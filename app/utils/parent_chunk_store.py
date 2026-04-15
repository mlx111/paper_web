"""父级分块文档存储（用于 Auto-merging Retriever）。"""  # 模块说明
import json  # JSON 读写
from pathlib import Path  # 路径处理
from typing import Dict, List  # 类型标注


class ParentChunkStore:
    """基于本地 JSON 的父级分块存储。"""  # 类说明

    def __init__(self, store_path: Path | None = None):
        base_dir = Path(__file__).resolve().parent  # 当前模块目录
        self.store_path = store_path or (base_dir.parent / "data" / "parent_chunks.json")  # 默认存储路径
        self.store_path.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在

    def _load(self) -> Dict[str, dict]:
        if not self.store_path.exists():
            return {}  # 文件不存在返回空
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)  # 读取 JSON
            if isinstance(data, dict):
                return data  # 正常返回字典
            return {}  # 类型不符则返回空
        except Exception:
            return {}  # 读取失败返回空

    def _save(self, data: Dict[str, dict]) -> None:
        tmp_path = self.store_path.with_suffix(".tmp")  # 临时文件路径
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)  # 写入 JSON
        tmp_path.replace(self.store_path)  # 原子替换

    def upsert_documents(self, docs: List[dict]) -> int:
        """写入/更新父级分块，返回写入条数。"""  # 方法说明
        if not docs:
            return 0  # 无数据直接返回

        store = self._load()  # 读取已有数据
        upserted = 0  # 计数器
        for doc in docs:
            chunk_id = (doc.get("chunk_id") or "").strip()  # 获取 chunk_id
            if not chunk_id:
                continue  # 无 ID 跳过
            store[chunk_id] = {  # 覆盖写入
                "text": doc.get("text", ""),
                "filename": doc.get("filename", ""),
                "file_type": doc.get("file_type", ""),
                "file_path": doc.get("file_path", ""),
                "page_number": doc.get("page_number", 0),
                "chunk_id": chunk_id,
                "parent_chunk_id": doc.get("parent_chunk_id", ""),
                "root_chunk_id": doc.get("root_chunk_id", ""),
                "chunk_level": int(doc.get("chunk_level", 0) or 0),
                "chunk_idx": int(doc.get("chunk_idx", 0) or 0),
            }
            upserted += 1  # 计数 +1

        self._save(store)  # 写回存储
        return upserted  # 返回写入数

    def get_documents_by_ids(self, chunk_ids: List[str]) -> List[dict]:
        if not chunk_ids:
            return []  # 空输入返回空
        store = self._load()  # 读取数据
        return [store[item] for item in chunk_ids if item in store]  # 返回命中项

    def delete_by_filename(self, filename: str) -> int:
        """按文件名删除父级分块，返回删除条数。"""  # 方法说明
        if not filename:
            return 0  # 空文件名直接返回

        store = self._load()  # 读取数据
        before = len(store)  # 删除前数量
        filtered = {  # 过滤掉指定文件名
            key: value for key, value in store.items()
            if value.get("filename") != filename
        }
        deleted = before - len(filtered)  # 计算删除数
        if deleted > 0:
            self._save(filtered)  # 保存新数据
        return deleted  # 返回删除数量
