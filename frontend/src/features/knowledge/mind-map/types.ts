// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

export interface MindMapNode {
  id: string
  parent_id: string | null
  title: string
}

export interface MindMapContent {
  root_id: string
  nodes: MindMapNode[]
}
