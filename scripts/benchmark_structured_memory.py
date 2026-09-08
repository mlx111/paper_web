"""
Benchmark script for structured memory: write classification + keyword recall.

Tests MemoryWriter (write gates, type inference, dedup) and
MemorySelector (keyword-based recall precision/recall).

Metrics:
  - Write success rate by type
  - Type classification accuracy (auto vs expected)
  - Low-value interception rate
  - Duplicate block rate
  - Keyword recall hit rate @ top-3 / top-5
  - Average recall count
  - Wrong recall rate
"""

from __future__ import annotations

import sys
import time
import tempfile
from pathlib import Path

_app_dir = str(Path(__file__).parent.parent / "app")
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

from services.memory.memory_types import MemoryEntry, MemoryType
from services.memory.memory_writer import MemoryWriter
from services.memory.memory_selector import MemorySelector


# ---------------------------------------------------------------------------
# Test conversations
# ---------------------------------------------------------------------------
# IMPORTANT: assistant responses must NOT contain LOW_VALUE_PATTERNS
# ("好的", "明白了", "收到", "谢谢", "知道了") or they get false-rejected.

WRITE_CASES: list[tuple[str, str, MemoryType | None, bool]] = [
    # --- User memories (should save) ---
    (
        "我是做自然语言处理的研究生，主要关注大模型评估方法",
        "已记录，NLP 方向 LLM evaluation 研究生。",
        MemoryType.USER, True,
    ),
    (
        "我偏好用 Python 和 PyTorch 做实验",
        "优先使用 PyTorch，已记录偏好。",
        MemoryType.USER, True,
    ),
    # --- Feedback memories (should save) ---
    (
        "不要每次都搜索那么多论文，先聚焦在最近三年的",
        "已调整，搜索范围限制在最近三年内。",
        MemoryType.FEEDBACK, True,
    ),
    (
        "你给的答案太长了，简洁一点",
        "已精简回答风格，后续更简洁。",
        MemoryType.FEEDBACK, True,
    ),
    (
        "不是这个意思，我是想让你对比方法A和B的差异",
        "重新对比方法 A 和 B 的差异。",
        MemoryType.FEEDBACK, True,
    ),
    # --- Project memories (should save) ---
    (
        "我们的论文需要在6月15号前提交到ACL",
        "ACL 截止日期 6 月 15 日，已记录。",
        MemoryType.PROJECT, True,
    ),
    (
        "下周需要完成实验部分的初稿",
        "实验初稿截止下周，已规划时间线。",
        MemoryType.PROJECT, True,
    ),
    (
        "我们计划用Qwen模型作为基座进行微调实验",
        "使用 Qwen 基座模型微调，已记录。",
        MemoryType.PROJECT, True,
    ),
    # --- Reference memories (should save) ---
    (
        "论文放在共享的arXiv collection里，链接是https://arxiv.org/mycollection",
        "arXiv collection 已记录。",
        MemoryType.REFERENCE, True,
    ),
    (
        "你可以参考这个GitHub仓库的实现：github.com/example/llm-eval",
        "GitHub 参考仓库已记录。",
        MemoryType.REFERENCE, True,
    ),
    # --- Low-value (should NOT be saved) ---
    ("谢谢", "不客气，有其他问题随时问。", None, False),
    ("好的", "嗯嗯", None, False),
    ("hello", "hi there", None, False),
    ("知道了", "有什么需要再找我。", None, False),
    # --- Code patterns (derivable in English, should NOT be saved) ---
    (
        "The file path is app/services/foo.py",
        "Noted the file path.",
        None, False,
    ),
]

# ---------------------------------------------------------------------------
# Recall test cases — use English queries + English-style content terms
# so that _select_keyword's re.findall(r"\w+", ...) can tokenize correctly.
# ---------------------------------------------------------------------------
RECALL_CONTENT: list[tuple[str, MemoryType]] = [
    ("user is a NLP graduate student focused on LLM evaluation methods", MemoryType.USER),
    ("user prefers using Python and PyTorch for experiments", MemoryType.USER),
    ("search should be limited to last three years per user request", MemoryType.FEEDBACK),
    ("user requires concise and brief answers", MemoryType.FEEDBACK),
    ("ACL paper submission deadline is June 15th", MemoryType.PROJECT),
    ("experiment draft is due next week", MemoryType.PROJECT),
    ("using Qwen model as base for fine-tuning experiments", MemoryType.PROJECT),
    ("reference papers stored in arXiv collection", MemoryType.REFERENCE),
    ("reference code available on GitHub repo", MemoryType.REFERENCE),
]

RECALL_QUERIES: list[tuple[str, str, bool]] = [
    # (query, expected_content_keyword, should_recall)
    ("what is the user's research direction", "NLP graduate", True),
    ("what framework does the user prefer", "Python and PyTorch", True),
    ("what is the search time range", "last three years", True),
    ("what is the answer style preference", "concise", True),
    ("when is the paper deadline", "June 15th", True),
    ("when is the experiment draft due", "next week", True),
    ("what base model is used", "Qwen model", True),
    ("where are reference papers stored", "arXiv collection", True),
    ("where is the reference code", "GitHub repo", True),
    # Negative cases (should NOT recall)
    ("what is the user's programming skill level", "NLP graduate", False),
    ("where is the conference venue", "June 15th", False),
    ("what training dataset is used", "Qwen model", False),
]

# ---------------------------------------------------------------------------
# Duplicate test cases
# ---------------------------------------------------------------------------
DUP_CASES: list[tuple[str, str, str]] = [
    ("user research direction", "user is a NLP graduate student focused on LLM evaluation methods for research work", "user is a NLP graduate student focused on LLM evaluation methods for research"),
    ("feedback preference", "user requires concise and brief answers from the assistant always", "user requires concise and brief answers from the assistant"),
]


# ---------------------------------------------------------------------------
# Write benchmark
# ---------------------------------------------------------------------------

def run_write_benchmark(writer: MemoryWriter) -> dict:
    results = []
    type_hits = 0
    type_total = 0
    low_value_caught = 0
    low_value_total = 0
    saved_count = 0
    saved_expected = 0
    gate_errors = []

    for user_msg, asst_msg, expected_type, should_save in WRITE_CASES:
        entry = writer.evaluate_and_save(user_msg, asst_msg, session_id="bench")
        actually_saved = entry is not None

        if should_save and actually_saved:
            saved_count += 1
            saved_expected += 1
            if expected_type and entry is not None:
                type_total += 1
                if entry.type == expected_type:
                    type_hits += 1
                else:
                    gate_errors.append(
                        f"  Type mismatch: expected={expected_type.value}, "
                        f"actual={entry.type.value}, msg='{user_msg[:30]}...'"
                    )
        elif should_save and not actually_saved:
            gate_errors.append(
                f"  False rejection: expected={expected_type.value if expected_type else 'None'}, "
                f"msg='{user_msg[:40]}...'"
            )
        elif not should_save and not actually_saved:
            low_value_caught += 1

        if not should_save:
            low_value_total += 1

        results.append({
            "user": user_msg[:50],
            "expected_save": should_save,
            "expected_type": expected_type.value if expected_type else None,
            "actually_saved": actually_saved,
            "actual_type": entry.type.value if entry else None,
            "correct": (should_save == actually_saved),
        })

    false_saves = sum(1 for r in results if not r["expected_save"] and r["actually_saved"])
    false_rejections = sum(1 for r in results if r["expected_save"] and not r["actually_saved"])

    return {
        "total_cases": len(WRITE_CASES),
        "saved_count": saved_count,
        "expected_saves": sum(1 for _, _, _, s in WRITE_CASES if s),
        "false_saves": false_saves,
        "false_rejections": false_rejections,
        "type_classification_accuracy": type_hits / type_total if type_total else 0,
        "type_total": type_total,
        "type_hits": type_hits,
        "low_value_interception_rate": low_value_caught / low_value_total if low_value_total else 0,
        "low_value_total": low_value_total,
        "low_value_caught": low_value_caught,
        "gate_errors": gate_errors,
        "details": results,
    }


def run_duplicate_benchmark(writer: MemoryWriter) -> dict:
    """Test duplicate detection — second write with same title should update in-place."""
    updated = 0
    total = 0
    details = []
    for title, content1, content2 in DUP_CASES:
        entry1 = writer.save_manual(title, content1, MemoryType.PROJECT, session_id="bench_dup")
        # Count memory files with this slug before second write
        slug = writer._memory_path(title)
        files_before = len(list(writer.storage_dir.glob(slug.name)))

        entry2 = writer.save_manual(title, content2, MemoryType.PROJECT, session_id="bench_dup")

        # After second write: should be same file (updated), not a new file
        files_after = len(list(writer.storage_dir.glob(slug.name)))
        no_new_file = files_after == files_before
        # Entry2 should exist (update) and have new content
        content_updated = entry2 is not None and entry2.content == content2

        total += 1
        if no_new_file and content_updated:
            updated += 1

        details.append({
            "title": title,
            "no_new_file": no_new_file,
            "content_updated": content_updated,
        })

    return {
        "total_dup_tests": total,
        "updated_in_place": updated,
        "dedup_handled_rate": updated / total if total else 0,
        "details": details,
    }


def run_recall_benchmark(storage_dir: Path) -> dict:
    """Save RECALL_CONTENT via save_manual, then query via select_sync."""
    writer = MemoryWriter(storage_dir)

    # Seed the memory store with known content
    saved_titles = []
    for content, mem_type in RECALL_CONTENT:
        title = f"bench_recall_{len(saved_titles)}"
        entry = writer.save_manual(title, content, mem_type, session_id="bench_recall")
        if entry:
            saved_titles.append(title)

    selector = MemorySelector(storage_dir)
    results = []
    recall_hits_at_3 = 0
    recall_hits_at_5 = 0
    recall_cases = sum(1 for _, _, should in RECALL_QUERIES if should)
    non_recall_cases = sum(1 for _, _, should in RECALL_QUERIES if not should)
    false_neg_list: list[tuple[str, str]] = []
    false_pos_list: list[tuple[str, str]] = []

    for query, expected_kw, should_recall in RECALL_QUERIES:
        selected = selector.select_sync(query, max_results=5)
        selected_contents = [s.content for s in selected]

        # Check if any selected memory contains the expected keyword
        found_in_3 = False
        found_in_5 = False
        for i, sc in enumerate(selected_contents):
            if expected_kw.lower() in sc.lower():
                if i < 3:
                    found_in_3 = True
                found_in_5 = True

        if should_recall:
            if found_in_3:
                recall_hits_at_3 += 1
            if found_in_5:
                recall_hits_at_5 += 1
            if not found_in_5:
                false_neg_list.append((query, expected_kw))
        else:
            if found_in_5:
                false_pos_list.append((query, expected_kw))

        results.append({
            "query": query,
            "expected_recall": should_recall,
            "recalled_in_top3": found_in_3,
            "recalled_in_top5": found_in_5,
            "selected_count": len(selected),
        })

    return {
        "memories_seeded": len(saved_titles),
        "total_recall_tests": len(RECALL_QUERIES),
        "recall_cases": recall_cases,
        "non_recall_cases": non_recall_cases,
        "recall_hits_at_3": recall_hits_at_3,
        "recall_hits_at_5": recall_hits_at_5,
        "recall_rate_top3": recall_hits_at_3 / max(recall_cases, 1),
        "recall_rate_top5": recall_hits_at_5 / max(recall_cases, 1),
        "false_positives": len(false_pos_list),
        "false_negatives": len(false_neg_list),
        "false_positive_rate": len(false_pos_list) / max(non_recall_cases, 1),
        "false_negative_rate": len(false_neg_list) / max(recall_cases, 1),
        "false_positive_details": false_pos_list,
        "false_negative_details": false_neg_list,
        "details": results,
    }


def main():
    with tempfile.TemporaryDirectory(prefix="memory_bench_") as tmp:
        storage_dir = Path(tmp)

        print("=" * 70)
        print("  结构化记忆基准测试")
        print("=" * 70)

        # ---- Write benchmark ----
        writer = MemoryWriter(storage_dir)
        print("\n[Write] 写入 + 分类 + 低价值拦截")
        t0 = time.perf_counter()
        w = run_write_benchmark(writer)
        wt = time.perf_counter() - t0
        print(f"  总用例: {w['total_cases']}")
        print(f"  预期保存: {w['expected_saves']}, 实际保存: {w['saved_count']}")
        print(f"  误保存 (不该保存却保存了): {w['false_saves']}")
        print(f"  漏保存 (该保存却没保存):   {w['false_rejections']}")
        print(f"  类型分类准确率: {w['type_classification_accuracy']:.0%} ({w['type_hits']}/{w['type_total']})")
        print(f"  低价值拦截率:   {w['low_value_interception_rate']:.0%} ({w['low_value_caught']}/{w['low_value_total']})")
        if w['gate_errors']:
            for e in w['gate_errors']:
                print(f"  ! {e}")

        # ---- Duplicate benchmark ----
        print("\n[Dup] 重复记忆拦截 (原地更新)")
        d = run_duplicate_benchmark(writer)
        print(f"  重复处理率: {d['dedup_handled_rate']:.0%} ({d['updated_in_place']}/{d['total_dup_tests']})")

        # ---- Recall benchmark ----
        # Use a fresh storage dir so recall content is deterministic
        print("\n[Recall] 关键词召回")
        recall_dir = Path(tmp) / "recall_db"
        recall_dir.mkdir()
        t0 = time.perf_counter()
        r = run_recall_benchmark(recall_dir)
        rt = time.perf_counter() - t0
        print(f"  种子记忆: {r['memories_seeded']} 条")
        print(f"  召回测试: {r['total_recall_tests']} (应召回 {r['recall_cases']}, 不应召回 {r['non_recall_cases']})")
        print(f"  Top-3 召回率: {r['recall_rate_top3']:.0%} ({r['recall_hits_at_3']}/{r['recall_cases']})")
        print(f"  Top-5 召回率: {r['recall_rate_top5']:.0%} ({r['recall_hits_at_5']}/{r['recall_cases']})")
        print(f"  误召回数:     {r['false_positives']} ({r['false_positive_rate']:.0%})")
        print(f"  漏召回数:     {r['false_negatives']} ({r['false_negative_rate']:.0%})")
        if r['false_negative_details']:
            print(f"  漏召回详情:")
            for q, kw in r['false_negative_details']:
                print(f"    query='{q}'  expected='{kw}'")
        if r['false_positive_details']:
            print(f"  误召回详情:")
            for q, kw in r['false_positive_details']:
                print(f"    query='{q}'  unexpected='{kw}'")

        # ---- Summary ----
        print(f"\n{'=' * 70}")
        print("  汇总")
        print(f"{'=' * 70}")
        print(f"  写入性能:            {w['total_cases']} cases in {wt*1000:.0f}ms")
        print(f"  类型分类准确率:      {w['type_classification_accuracy']:.0%}")
        print(f"  低价值拦截率:        {w['low_value_interception_rate']:.0%}")
        print(f"  重复记忆处理率:      {d['dedup_handled_rate']:.0%}")
        print(f"  Top-3 召回率:        {r['recall_rate_top3']:.0%}")
        print(f"  Top-5 召回率:        {r['recall_rate_top5']:.0%}")
        print(f"  误召回率:            {r['false_positive_rate']:.0%}")
        print(f"  召回性能:            {r['total_recall_tests']} queries in {rt*1000:.0f}ms")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
