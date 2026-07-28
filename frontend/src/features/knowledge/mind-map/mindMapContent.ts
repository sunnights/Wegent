// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import type { MindMapContent, MindMapNode } from './types'

const MAX_NODES = 200
type Translate = (key: string, options?: Record<string, string>) => string

interface ParsedLine {
  indent: number
  id: string
  title: string
}

function extractNode(line: string, index: number): ParsedLine | null {
  const indent = line.match(/^[\t ]*/)?.[0].replace(/\t/g, '  ').length ?? 0
  const value = line
    .trim()
    .replace(/::icon\([^)]*\)/g, '')
    .replace(/:::[\w-]+/g, '')
    .trim()

  if (!value || value.startsWith('%%') || value.startsWith('::')) return null

  const shapes = [
    /^([A-Za-z0-9_-]+)\(\(([\s\S]+)\)\)$/,
    /^([A-Za-z0-9_-]+)\{\{([\s\S]+)\}\}$/,
    /^([A-Za-z0-9_-]+)\[([\s\S]+)\]$/,
    /^([A-Za-z0-9_-]+)\(([\s\S]+)\)$/,
    /^([A-Za-z0-9_-]+)\)\)([\s\S]+)\(\($/,
    /^([A-Za-z0-9_-]+)\)([\s\S]+)\($/,
  ]

  for (const shape of shapes) {
    const match = value.match(shape)
    if (match) {
      return {
        indent,
        id: match[1],
        title: match[2].replace(/<br\s*\/?>/gi, ' ').trim(),
      }
    }
  }

  return {
    indent,
    id: `mind-map-node-${index}`,
    title: value.replace(/<br\s*\/?>/gi, ' ').trim(),
  }
}

export function isMermaidMindMap(code: string): boolean {
  return /^\s*mindmap\b/i.test(code)
}

export function parseMermaidMindMap(code: string): MindMapContent | null {
  if (!isMermaidMindMap(code)) return null

  const parsedLines = code
    .split('\n')
    .slice(1)
    .map(extractNode)
    .filter((line): line is ParsedLine => line !== null)

  if (parsedLines.length === 0 || parsedLines.length > MAX_NODES) return null

  const nodes: MindMapNode[] = []
  const ancestors: Array<{ indent: number; id: string }> = []
  const usedIds = new Set<string>()

  for (const line of parsedLines) {
    while (ancestors.length > 0 && ancestors[ancestors.length - 1].indent >= line.indent) {
      ancestors.pop()
    }

    if (nodes.length > 0 && ancestors.length === 0) return null

    let id = line.id
    let suffix = 2
    while (usedIds.has(id)) {
      id = `${line.id}-${suffix}`
      suffix += 1
    }
    usedIds.add(id)

    nodes.push({
      id,
      parent_id: ancestors[ancestors.length - 1]?.id ?? null,
      title: line.title,
    })
    ancestors.push({ indent: line.indent, id })
  }

  return {
    root_id: nodes[0].id,
    nodes,
  }
}

export function getMindMapNodePath(content: MindMapContent, nodeId: string): MindMapNode[] {
  const nodesById = new Map(content.nodes.map(node => [node.id, node]))
  const path: MindMapNode[] = []
  const visited = new Set<string>()
  let current = nodesById.get(nodeId)

  while (current && !visited.has(current.id)) {
    path.unshift(current)
    visited.add(current.id)
    current = current.parent_id ? nodesById.get(current.parent_id) : undefined
  }
  return path
}

export function buildMindMapQuestion(
  content: MindMapContent,
  nodeId: string,
  t: Translate
): string {
  const path = getMindMapNodePath(content, nodeId)
  const node = path[path.length - 1]
  if (!node) return ''

  return [
    t('artifact.mindMap.question', { title: node.title }),
    t('artifact.mindMap.path', { path: path.map(item => item.title).join(' > ') }),
    t('artifact.mindMap.instruction'),
  ].join('\n')
}
