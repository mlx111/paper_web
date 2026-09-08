# MyPaperWeb 后端镜像
# 国内构建可覆盖依赖源：docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# 基础镜像显式走已验证的国内镜像站（如在海外构建，可改回 python:3.11-slim）
FROM docker.1ms.run/library/python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先装依赖（requirements.txt 不变时命中 Docker 层缓存）
# 大依赖包（spacy 等）较多，放宽超时与重试
COPY requirements.txt ./
RUN pip install --no-cache-dir --default-timeout=300 --retries 5 -r requirements.txt

# 业务代码：本地从 app/ 目录启动（uvicorn main:app），容器内保持一致
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

WORKDIR /app/app

# 运行时数据目录（与代码中的路径约定一致：项目根=/app）
# /app/uploads 上传文件；/app/app/data 笔记/记忆/checkpoint/研究产物；/app/workspace Agent 文件工作区
RUN mkdir -p /app/uploads /app/app/data /app/workspace

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
