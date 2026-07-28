// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import {
  buildMindMapQuestion,
  getMindMapNodePath,
  parseMermaidMindMap,
} from '@/features/knowledge/mind-map/mindMapContent'

const code = `mindmap
  root((AB 实验))
    flow[创建流程]
      filter(过滤条件)
      ::icon(fa fa-filter)
    facts{{关键事实}}`

describe('Mermaid mind map content', () => {
  it('parses Mermaid indentation, shapes, and stable IDs into a tree', () => {
    const parsed = parseMermaidMindMap(code)

    expect(parsed).toEqual({
      root_id: 'root',
      nodes: [
        { id: 'root', parent_id: null, title: 'AB 实验' },
        { id: 'flow', parent_id: 'root', title: '创建流程' },
        { id: 'filter', parent_id: 'flow', title: '过滤条件' },
        { id: 'facts', parent_id: 'root', title: '关键事实' },
      ],
    })
  })

  it('supports plain Mermaid node labels and rejects multiple roots', () => {
    const parsed = parseMermaidMindMap('mindmap\n  Topic\n    Child topic')

    expect(parsed?.nodes.map(node => node.title)).toEqual(['Topic', 'Child topic'])
    expect(parseMermaidMindMap('mindmap\n  Root one\n  Root two')).toBeNull()
  })

  it('builds a follow-up question with the full node path', () => {
    const parsed = parseMermaidMindMap(code)!
    const t = (key: string, options?: Record<string, string>) =>
      ({
        'artifact.mindMap.question': `Explain ${options?.title}`,
        'artifact.mindMap.path': `Path: ${options?.path}`,
        'artifact.mindMap.instruction': 'Cite sources',
      })[key] ?? key

    expect(getMindMapNodePath(parsed, 'filter').map(node => node.title)).toEqual([
      'AB 实验',
      '创建流程',
      '过滤条件',
    ])
    expect(buildMindMapQuestion(parsed, 'filter', t)).toBe(
      'Explain 过滤条件\nPath: AB 实验 > 创建流程 > 过滤条件\nCite sources'
    )
  })
})
