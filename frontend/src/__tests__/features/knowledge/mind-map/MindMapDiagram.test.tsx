// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react'
import MindMapDiagram from '@/features/knowledge/mind-map/MindMapDiagram'

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) =>
      ({
        'artifact.mindMap.question': `Explain ${options?.title}`,
        'artifact.mindMap.path': `Path: ${options?.path}`,
        'artifact.mindMap.instruction': 'Cite sources',
      })[key] ?? key,
  }),
}))

jest.mock('@/features/knowledge/mind-map/InteractiveMindMap', () => ({
  InteractiveMindMap: ({ onAskNode }: { onAskNode?: (nodeId: string) => void }) => (
    <button type="button" onClick={() => onAskNode?.('child')}>
      Ask child
    </button>
  ),
}))

jest.mock('@/components/common/MermaidDiagram', () => ({
  __esModule: true,
  default: () => <div>Generic Mermaid</div>,
}))

it('turns a mind-map node action into a task follow-up message', () => {
  const onAskNode = jest.fn()
  render(
    <MindMapDiagram code={'mindmap\n  root((Root))\n    child[Child]'} onAskNode={onAskNode} />
  )

  fireEvent.click(screen.getByText('Ask child'))

  expect(onAskNode).toHaveBeenCalledWith('Explain Child\nPath: Root > Child\nCite sources')
})

it('falls back to the generic renderer when Mermaid cannot form a tree', () => {
  render(<MindMapDiagram code={'mindmap\n  Root one\n  Root two'} />)

  expect(screen.getByText('Generic Mermaid')).toBeInTheDocument()
})
