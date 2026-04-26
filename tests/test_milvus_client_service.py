import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

documents_module = types.ModuleType("langchain_core.documents")
documents_module.Document = object
sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
sys.modules["langchain_core.documents"] = documents_module

loguru_module = types.ModuleType("loguru")
loguru_module.logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["loguru"] = loguru_module

pymilvus_module = types.ModuleType("pymilvus")
pymilvus_module.AnnSearchRequest = object
pymilvus_module.DataType = types.SimpleNamespace(
    INT64="INT64",
    FLOAT_VECTOR="FLOAT_VECTOR",
    SPARSE_FLOAT_VECTOR="SPARSE_FLOAT_VECTOR",
    VARCHAR="VARCHAR",
)
pymilvus_module.MilvusClient = object
pymilvus_module.RRFRanker = object
sys.modules["pymilvus"] = pymilvus_module

from services.mlivus_client_service import MilvusManager


class _Field:
    def __init__(self, name, params=None, dim=None):
        self.name = name
        self.params = params or {}
        self.dim = dim


class _Schema:
    def __init__(self, fields):
        self.fields = fields


class _CollectionInfo:
    def __init__(self, fields):
        self.schema = _Schema(fields)


class _ExistingCollectionClient:
    def __init__(self, collection_info):
        self.collection_info = collection_info

    def has_collection(self, collection_name):
        return True

    def describe_collection(self, collection_name):
        return self.collection_info


class MilvusManagerDimensionTest(unittest.TestCase):
    def test_reads_dense_dimension_from_object_schema(self):
        manager = MilvusManager()
        client = _ExistingCollectionClient(
            _CollectionInfo([
                _Field("id"),
                _Field("dense_embedding", params={"dim": 1024}),
            ])
        )

        self.assertEqual(manager._get_collection_dense_dim(client), 1024)

    def test_existing_collection_dimension_mismatch_raises(self):
        manager = MilvusManager()
        manager.client = _ExistingCollectionClient(
            _CollectionInfo([
                _Field("dense_embedding", params={"dim": 768}),
            ])
        )

        with self.assertRaises(ValueError):
            manager.init_collection(dense_dim=1024)


if __name__ == "__main__":
    unittest.main()
