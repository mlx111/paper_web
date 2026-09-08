from __future__ import annotations

from .assembler import ContextAssembler
from .compressor import ContextCompressor
from .context_config import ContextConfig
from .gatherer import ContextGatherer
from .selector import ContextSelector
from .structurer import ContextStructurer
from .types import ContextBundle


class ContextBuilder:
    """
    上下文工程的总入口。

    整条链路是：
    Gather -> Select -> Structure -> Compress -> Assemble

    这几个阶段各做各的事，不要互相耦合。
    """

    def __init__(
        self,
        history_loader,
        knowledge_retriever=None,
        parent_chunk_retriever=None,
        notes_loader=None,
        memory_loader=None,
        rerank_fn=None,
        config: ContextConfig | None = None,
    ):

        # 统一配置，后面所有组件都共享这一份预算
        self.config = config or ContextConfig()

        # 历史、检索源都从这里收集
        self.gatherer = ContextGatherer(
            history_loader=history_loader,
            knowledge_retriever=knowledge_retriever,
            parent_chunk_retriever=parent_chunk_retriever,
            notes_loader=notes_loader,
            memory_loader=memory_loader,
            config=self.config,
        )

        # 从候选里挑真正有用的内容
        self.selector = ContextSelector(rerank_fn=rerank_fn)

        # 把选中的内容整理成结构化块
        self.structurer = ContextStructurer(self.config)

        # 压缩上下文，避免超预算
        self.compressor = ContextCompressor(self.config)

        # 最后把上下文拼成模型可读文本
        self.assembler = ContextAssembler(self.config)

    def build(
        self,
        question: str,
        session_id: str,
        mode: str = "deep",
        top_k: int = 8,
        evidence_top_k: int = 6,
    ) -> ContextBundle:
        """
        构建一次完整的上下文包。

        参数说明：
        - question：当前用户问题
        - session_id：会话 ID
        - mode：quick / deep / router
        - top_k：收集候选时抓多少条
        - evidence_top_k：最终保留多少条证据
        """
        # 1. 先收集候选和历史
        candidates, history = self.gatherer.gather(
            question=question,
            session_id=session_id,
            top_k=top_k,
        )

        # 2. 从候选里挑出更相关的证据
        evidence = self.selector.select(
            question=question,
            candidates=candidates,
            top_k=evidence_top_k,
        )

        # 3. 把证据和历史整理成结构化 packet
        packets = self.structurer.structure(
            question=question,
            session_id=session_id,
            history=history,
            evidence=evidence,
            candidates=candidates,
            mode=mode,
        )

        # 4. 再压缩一遍，控制最终预算
        compressed_packets = self.compressor.compress(packets)

        # 5. 组装成最终上下文包
        return self.assembler.assemble_from_packets(
            question=question,
            session_id=session_id,
            history=history,
            evidence=evidence,
            packets=compressed_packets,
            candidates=candidates,
            mode=mode,
        )
