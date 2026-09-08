from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_start_script_checks_all_existing_milvus_containers_before_compose_up():
    text = (ROOT / "start-windows.bat").read_text(encoding="utf-8")

    assert 'docker ps -a --format "{{.Names}}" | findstr "milvus-"' in text
    assert "Found existing Milvus containers" in text
    assert "docker compose -f vector-database.yml down" in text
    assert "docker compose -f vector-database.yml up -d" in text
    assert "docker rm -f milvus-etcd milvus-minio milvus-standalone milvus-attu" in text


def test_stop_script_uses_ps_a_to_cleanup_stopped_or_created_milvus_containers():
    text = (ROOT / "stop-windows.bat").read_text(encoding="utf-8")

    assert 'docker ps -a --format "{{.Names}}" | findstr "milvus-"' in text
    assert "Milvus containers do not exist" in text
    assert "docker compose -f vector-database.yml down" in text
    executable_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().lower().startswith("echo")
    ]
    assert "docker compose -f vector-database.yml down -v" not in executable_lines
