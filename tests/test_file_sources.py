import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = [
    "fastapi",
    "fastapi.responses",
    "loguru",
    "sse_starlette",
    "sse_starlette.sse",
    "agents.file_agent_service",
    "models.request",
    "models.response",
    "services.chunk_image_store_service",
    "services.temp_file_service",
    "services.vector_index_service",
    "utils.rag_utils",
]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in STUB_MODULES}

for name in STUB_MODULES:
    sys.modules.setdefault(name, types.ModuleType(name))


class _Router:
    def __init__(self, *args, **kwargs):
        pass

    def post(self, *args, **kwargs):
        return lambda fn: fn

    def get(self, *args, **kwargs):
        return lambda fn: fn


class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        self.status_code = status_code
        self.detail = detail


class _Document:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


sys.modules["fastapi"].APIRouter = _Router
sys.modules["fastapi"].File = lambda *args, **kwargs: None
sys.modules["fastapi"].Form = lambda *args, **kwargs: None
sys.modules["fastapi"].HTTPException = _HTTPException
sys.modules["fastapi"].UploadFile = object
sys.modules["fastapi.responses"].FileResponse = object
sys.modules["fastapi.responses"].JSONResponse = object
sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["sse_starlette.sse"].EventSourceResponse = object
sys.modules["agents.file_agent_service"].file_agent_service = types.SimpleNamespace()
sys.modules["models.request"].ChatRequest = object
sys.modules["models.request"].ClearRequest = object
sys.modules["models.response"].ApiResponse = object
sys.modules["models.response"].SessionInfoResponse = object
sys.modules["services.chunk_image_store_service"].default_chunk_image_store = types.SimpleNamespace()
sys.modules["services.temp_file_service"].temp_file_service = types.SimpleNamespace(
    build_context_text=lambda session_id: "",
    clear_session_temp_files=lambda session_id: True,
)
sys.modules["services.vector_index_service"].vector_index_service = types.SimpleNamespace()
sys.modules["utils.rag_utils"].rag_utils_service = types.SimpleNamespace()

from routers.file import _format_source_doc


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class FileSourcesTest(unittest.TestCase):
    def test_format_source_doc_returns_frontend_friendly_source(self):
        doc = _Document(
            "这是一段很长的论文内容。" * 30,
            {
                "filename": "paper.pdf",
                "page_number": 2,
                "chunk_id": "paper.pdf::p2::l3::4",
                "score": 0.812345,
            },
        )

        source = _format_source_doc(doc)

        self.assertEqual(source["filename"], "paper.pdf")
        self.assertEqual(source["page_number"], 2)
        self.assertEqual(source["chunk_id"], "paper.pdf::p2::l3::4")
        self.assertEqual(source["score"], 0.8123)
        self.assertLessEqual(len(source["preview"]), 243)


if __name__ == "__main__":
    unittest.main()
