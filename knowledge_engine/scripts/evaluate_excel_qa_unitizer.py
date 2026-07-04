# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Evaluate Excel row-aware Q&A unitization on a local workbook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.ingestion.excel_qa_unitizer import (
    build_excel_qa_pair_nodes_from_file,
)


def evaluate(source: Path) -> dict[str, Any]:
    result = build_excel_qa_pair_nodes_from_file(
        str(source),
        source_file=source.name,
    )
    if result is None:
        return {
            "source": str(source),
            "detected": False,
            "qa_pair_count": 0,
            "skipped_row_count": 0,
            "sheet_summaries": [],
            "samples": [],
        }

    return {
        "source": str(source),
        "detected": result.detected,
        "confidence": result.confidence,
        "qa_pair_count": result.qa_row_count,
        "skipped_row_count": result.skipped_row_count,
        "sheet_summaries": [
            {
                "sheet_name": summary.sheet_name,
                "header_row": summary.header_row,
                "data_row_count": summary.data_row_count,
                "qa_row_count": summary.qa_row_count,
                "skipped_row_count": summary.skipped_row_count,
                "confidence": summary.confidence,
                "question_column": summary.mapping.question_column,
                "answer_columns": summary.mapping.answer_columns,
                "alternate_question_columns": (
                    summary.mapping.alternate_question_columns
                ),
                "context_columns": summary.mapping.context_columns,
            }
            for summary in result.sheet_summaries
        ],
        "samples": [
            {
                "index": index,
                "content": node.text,
                "metadata": {
                    "sheet_name": node.metadata.get("sheet_name"),
                    "row_number": node.metadata.get("row_number"),
                    "question": node.metadata.get("question"),
                    "alternate_questions": node.metadata.get("alternate_questions", []),
                    "context_fields": node.metadata.get("context_fields", {}),
                },
            }
            for index, node in enumerate(result.nodes[:5])
        ],
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "---",
        "sidebar_position: 1",
        "---",
        "",
        "# Excel FAQ Row-Aware 索引评估",
        "",
        "## 摘要",
        "",
        f"- 源文件：`{payload['source']}`",
        f"- 是否识别为 FAQ：{payload['detected']}",
        f"- Q&A 节点数：{payload['qa_pair_count']}",
        f"- 跳过行数：{payload['skipped_row_count']}",
    ]
    if payload.get("confidence") is not None:
        lines.append(f"- 置信度：{payload['confidence']:.4f}")

    lines.extend(
        [
            "",
            "## Sheet 识别结果",
            "",
            "| sheet | header row | data rows | qa rows | skipped | confidence | question | answers | alternates | context |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for summary in payload["sheet_summaries"]:
        lines.append(
            f"| {summary['sheet_name']} | {summary['header_row']} | "
            f"{summary['data_row_count']} | {summary['qa_row_count']} | "
            f"{summary['skipped_row_count']} | {summary['confidence']:.4f} | "
            f"{summary['question_column']} | "
            f"{', '.join(summary['answer_columns'])} | "
            f"{', '.join(summary['alternate_question_columns']) or '-'} | "
            f"{', '.join(summary['context_columns']) or '-'} |"
        )

    lines.extend(
        [
            "",
            "## 前 5 个节点预览",
            "",
        ]
    )
    for sample in payload["samples"]:
        metadata = sample["metadata"]
        lines.extend(
            [
                f"### #{sample['index']} {metadata.get('sheet_name')} 第 {metadata.get('row_number')} 行",
                "",
                "```text",
                sample["content"],
                "```",
                "",
                f"- question: {metadata.get('question')}",
                f"- alternate_questions: {metadata.get('alternate_questions')}",
                f"- context_fields: {metadata.get('context_fields')}",
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    payload = evaluate(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(args.report, payload)


if __name__ == "__main__":
    main()
