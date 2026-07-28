// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useCallback, useMemo } from 'react'
import MermaidDiagram from '@/components/common/MermaidDiagram'
import { useTranslation } from '@/hooks/useTranslation'
import { InteractiveMindMap } from './InteractiveMindMap'
import { buildMindMapQuestion, parseMermaidMindMap } from './mindMapContent'

interface MindMapDiagramProps {
  code: string
  onAskNode?: (message: string) => void
}

export default function MindMapDiagram({ code, onAskNode }: MindMapDiagramProps) {
  const { t } = useTranslation('knowledge')
  const content = useMemo(() => parseMermaidMindMap(code), [code])
  const handleAskNode = useCallback(
    (nodeId: string) => {
      if (!content || !onAskNode) return
      const message = buildMindMapQuestion(content, nodeId, t)
      if (message) onAskNode(message)
    },
    [content, onAskNode, t]
  )

  if (!content) {
    return <MermaidDiagram code={code} />
  }

  return <InteractiveMindMap content={content} onAskNode={onAskNode ? handleAskNode : undefined} />
}
