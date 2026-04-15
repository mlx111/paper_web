"""Embedding 服务，支持稠密向量和 BM25 稀疏向量。"""

import math
import re
from collections import Counter

import jieba
import requests
from loguru import logger

from settings.config import config


class Embodedings:
    def __init__(self) -> None:
        self.api_key = config.DASHSCOPE_API_KEY
        self.base_url = config.DASHSCOPE_API_BASE
        self.embodeding = config.embedding_model_name

        self.k1 = 1.5
        self.b = 0.75
        self._vocab: dict[str, int] = {}
        self._vocab_counter = 0
        self._doc_freq: Counter[str] = Counter()
        self._total_docs = 0
        self._avg_doc_len = 0.0
        self.STOPWORDS = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "and", "or", "but", "to", "of", "in", "on", "at", "for", "by", "with",
            "from", "as", "that", "this", "these", "those", "it", "its",
        }
        logger.info("Embedding 服务初始化完成")

    def bm25_preprocess(self, text: str) -> list[str]:
        try:
            if not text:
                logger.info("BM25 预处理完成，输入为空")
                return []

            text = text.lower().strip()
            text = text.replace("cpu usage", "cpu_usage")
            text = text.replace("memory usage", "memory_usage")
            text = text.replace("disk usage", "disk_usage")
            text = re.sub(r"[^\u4e00-\u9fffa-z0-9_\-\.]+", " ", text)

            raw_tokens = jieba.lcut(text, cut_all=False)
            tokens: list[str] = []
            for token in raw_tokens:
                token = token.strip()
                if not token:
                    continue
                if re.fullmatch(r"[_\-.]+", token):
                    continue
                token = re.sub(r"[_\-.]{2,}", "_", token).strip("_.-")
                if not token:
                    continue
                if token in self.STOPWORDS:
                    continue
                if len(token) == 1 and re.fullmatch(r"[a-z]", token):
                    continue
                tokens.append(token)

            logger.info("BM25 预处理完成，生成 {} 个词", len(tokens))
            return tokens
        except Exception as exc:
            logger.error("BM25 预处理失败: {}", exc)
            raise

    def get_emboddings(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.embodeding,
            "input": texts,
            "encoding_format": "float",
        }

        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]]
            logger.info("稠密向量生成完成，文本数: {}", len(embeddings))
            return embeddings
        except Exception as exc:
            logger.error("稠密向量生成失败: {}", exc)
            raise Exception(f"embedding API 调用失败: {exc}") from exc

    def fit_corpus(self, texts: list[str]):
        try:
            self._vocab = {}
            self._vocab_counter = 0
            self._doc_freq = Counter()
            self._total_docs = len(texts)
            total_len = 0

            for text in texts:
                tokens = self.bm25_preprocess(text)
                total_len += len(tokens)
                for token in set(tokens):
                    self._doc_freq[token] += 1
                    if token not in self._vocab:
                        self._vocab[token] = self._vocab_counter
                        self._vocab_counter += 1

            self._avg_doc_len = total_len / self._total_docs if self._total_docs > 0 else 1.0
            logger.info(
                "BM25 语料拟合完成，文档数: {}，词表大小: {}",
                self._total_docs,
                len(self._vocab),
            )
        except Exception as exc:
            logger.error("BM25 语料拟合失败: {}", exc)
            raise

    def get_sparse_embedding(self, text: str) -> dict[int, float]:
        try:
            tokens = self.bm25_preprocess(text)
            doc_len = len(tokens)
            tf = Counter(tokens)
            sparse_vector: dict[int, float] = {}

            for token, freq in tf.items():
                if token not in self._vocab:
                    self._vocab[token] = self._vocab_counter
                    self._vocab_counter += 1

                idx = self._vocab[token]
                df = self._doc_freq.get(token, 0)
                if df == 0:
                    idf = math.log((self._total_docs + 1) / 1)
                else:
                    idf = math.log((self._total_docs - df + 0.5) / (df + 0.5) + 1)

                numerator = freq * (self.k1 + 1)
                denominator = freq + self.k1 * (
                    1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1)
                )
                score = idf * numerator / denominator
                if score > 0:
                    sparse_vector[idx] = float(score)

            logger.info("稀疏向量生成完成，非零维度数: {}", len(sparse_vector))
            return sparse_vector
        except Exception as exc:
            logger.error("稀疏向量生成失败: {}", exc)
            raise

    def get_sparse_embeddings(self, texts: list[str]) -> list[dict[int, float]]:
        try:
            result = [self.get_sparse_embedding(text) for text in texts]
            logger.info("批量稀疏向量生成完成，文本数: {}", len(result))
            return result
        except Exception as exc:
            logger.error("批量稀疏向量生成失败: {}", exc)
            raise

    def get_all_embeddings(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[dict[int, float]]]:
        try:
            dense_embeddings = self.get_emboddings(texts)
            sparse_embeddings = self.get_sparse_embeddings(texts)
            logger.info("混合向量生成完成，文本数: {}", len(texts))
            return dense_embeddings, sparse_embeddings
        except Exception as exc:
            logger.error("混合向量生成失败: {}", exc)
            raise

    def embed_query(self, text: str) -> list[list[float]]:
        try:
            if not text or not text.strip():
                raise ValueError("查询文本不能为空")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.embodeding,
                "input": text,
                "encoding_format": "float",
            }
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]]
            logger.info("查询向量生成完成，返回 {} 条向量", len(embeddings))
            return embeddings
        except Exception as exc:
            logger.error("查询向量生成失败: {}", exc)
            raise Exception(f"embedding API 调用失败: {exc}") from exc


embodeding_service = Embodedings()
