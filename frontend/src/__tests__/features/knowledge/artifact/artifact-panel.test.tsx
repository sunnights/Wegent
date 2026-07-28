// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react'
import { ArtifactPanel } from '@/features/knowledge/artifact/components/ArtifactPanel'

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

describe('ArtifactPanel', () => {
  it('opens every workshop capability as a task draft', () => {
    const onCreateDraft = jest.fn()
    render(<ArtifactPanel availableDocumentCount={3} onCreateDraft={onCreateDraft} />)

    fireEvent.click(screen.getByTestId('artifact-type-mind-map'))
    fireEvent.click(screen.getByTestId('artifact-type-presentation'))
    fireEvent.click(screen.getByTestId('artifact-type-briefing'))

    expect(onCreateDraft.mock.calls).toEqual([['mind_map'], ['presentation'], ['briefing']])
    expect(screen.queryByText('artifact.recentGenerations')).not.toBeInTheDocument()
  })

  it('disables generation when the knowledge base is empty', () => {
    render(<ArtifactPanel availableDocumentCount={0} onCreateDraft={jest.fn()} />)

    expect(screen.getByTestId('artifact-type-mind-map')).toBeDisabled()
    expect(screen.getByTestId('artifact-type-presentation')).toBeDisabled()
    expect(screen.getByTestId('artifact-type-briefing')).toBeDisabled()
    expect(screen.getByText('artifact.noDocumentsHint')).toBeInTheDocument()
  })
})
