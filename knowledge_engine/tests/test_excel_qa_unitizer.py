# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from openpyxl import Workbook

from knowledge_engine.ingestion.excel_qa_unitizer import (
    build_excel_qa_pair_nodes_from_file,
)


def _write_workbook(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    for sheet_name, rows in sheets.items():
        sheet = workbook.create_sheet(sheet_name)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


def test_excel_qa_unitizer_supports_minimal_question_answer_columns(tmp_path):
    path = tmp_path / "minimal.xlsx"
    _write_workbook(
        path,
        {
            "FAQ": [
                ["Q", "A"],
                ["如何找回登录名？", "请通过账号找回流程提交申请。"],
                ["如何修改手机号？", "请在账号安全设置中完成验证后修改。"],
            ]
        },
    )

    result = build_excel_qa_pair_nodes_from_file(str(path), source_file="minimal.xlsx")

    assert result is not None
    assert result.detected is True
    assert result.qa_row_count == 2
    assert result.skipped_row_count == 0
    assert len(result.nodes) == 2

    first = result.nodes[0]
    assert first.metadata["node_role"] == "qa_pair"
    assert first.metadata["source_format"] == "excel_faq"
    assert first.metadata["question"] == "如何找回登录名？"
    assert first.metadata["alternate_questions"] == []
    assert first.metadata["context_fields"] == {}
    assert first.metadata["sheet_name"] == "FAQ"
    assert first.metadata["row_number"] == 2
    assert first.text.startswith("Q: 如何找回登录名？")
    assert "A: 请通过账号找回流程提交申请。" in first.text
    assert first.metadata["retrieval_text"].startswith("Question: 如何找回登录名？")


def test_excel_qa_unitizer_preserves_alternates_and_context_fields(tmp_path):
    path = tmp_path / "customer-service.xlsx"
    _write_workbook(
        path,
        {
            "Sheet1": [
                ["标准Q", "相似Q", "一级分类", "内容", "内部流程标记"],
                [
                    "微博登录不上账号",
                    "微博出现登录不上怎么办;微博为什么登录不上",
                    "登录与账号找回",
                    "答案：请提交账号登录问题处理流程。",
                    "是",
                ],
                [
                    "微博忘记登录名",
                    "微博找回登录名怎么操作|微博登录名忘了",
                    "登录与账号找回",
                    "答案：请通过找回登录名入口处理。",
                    "是",
                ],
            ]
        },
    )

    result = build_excel_qa_pair_nodes_from_file(
        str(path), source_file="customer-service.xlsx"
    )

    assert result is not None
    assert result.qa_row_count == 2
    node = result.nodes[0]
    assert node.metadata["alternate_questions"] == [
        "微博出现登录不上怎么办",
        "微博为什么登录不上",
    ]
    assert node.metadata["context_fields"] == {
        "一级分类": "登录与账号找回",
        "内部流程标记": "是",
    }
    assert (
        "Alternate questions: 微博出现登录不上怎么办; 微博为什么登录不上"
        in node.metadata["retrieval_text"]
    )
    assert (
        "Context: 一级分类=登录与账号找回; 内部流程标记=是"
        in node.metadata["retrieval_text"]
    )


def test_excel_qa_unitizer_skips_non_faq_workbook(tmp_path):
    path = tmp_path / "metrics.xlsx"
    _write_workbook(
        path,
        {
            "Metrics": [
                ["日期", "访问量", "转化率"],
                ["2026-07-01", "100", "0.12"],
                ["2026-07-02", "120", "0.15"],
            ]
        },
    )

    result = build_excel_qa_pair_nodes_from_file(str(path), source_file="metrics.xlsx")

    assert result is None


def test_excel_qa_unitizer_handles_multiple_sheets_and_skips_empty_answers(tmp_path):
    path = tmp_path / "multi.xlsx"
    _write_workbook(
        path,
        {
            "Login": [
                ["问题", "答案", "渠道"],
                ["怎么找回登录名？", "通过找回登录名入口处理。", "App"],
                ["空答案问题", "", "App"],
                ["怎么修改密码？", "在账号安全中修改密码。", "Web"],
            ],
            "PlainData": [
                ["城市", "数量"],
                ["北京", "10"],
                ["上海", "20"],
            ],
        },
    )

    result = build_excel_qa_pair_nodes_from_file(str(path), source_file="multi.xlsx")

    assert result is not None
    assert result.qa_row_count == 2
    assert result.skipped_row_count == 1
    assert len(result.sheet_summaries) == 1
    assert result.sheet_summaries[0].sheet_name == "Login"
    assert all(node.metadata["sheet_name"] == "Login" for node in result.nodes)
    assert result.nodes[0].metadata["context_fields"] == {"渠道": "App"}
