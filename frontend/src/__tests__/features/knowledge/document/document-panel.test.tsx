// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DocumentPanel } from '@/features/knowledge/document/components/DocumentPanel'
import type { KnowledgeBase, KnowledgeDocument } from '@/types/knowledge'

const mockDocumentDetailDialog = jest.fn((_props: unknown) => null)
const mockArtifactSourceSelector = jest.fn((_props: unknown) => null)
const mockCreateDocument = jest.fn()
const mockFindDocumentForDeepLink = jest.fn()

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

jest.mock('@/features/knowledge/artifact/components/ArtifactPanel', () => ({
  ArtifactPanel: ({ onCreateDraft }: { onCreateDraft: (capability: string) => void }) => (
    <button data-testid="mock-create-ppt-draft" onClick={() => onCreateDraft('presentation')} />
  ),
}))

jest.mock('@/features/knowledge/artifact/components/ArtifactSourceSelector', () => ({
  ArtifactSourceSelector: (props: unknown) => mockArtifactSourceSelector(props),
}))

jest.mock('@/features/knowledge/document/components/DocumentUpload', () => ({
  DocumentUpload: ({
    open,
    onTableAdd,
  }: {
    open: boolean
    onTableAdd?: (data: { name: string; source_config: { url: string } }) => Promise<void>
  }) =>
    open ? (
      <button
        data-testid="mock-table-add"
        onClick={() =>
          void onTableAdd?.({
            name: 'Sales table',
            source_config: { url: 'https://example.com/table' },
          })
        }
      />
    ) : null,
}))

jest.mock('@/features/knowledge/document/components/DocumentDetailDialog', () => ({
  DocumentDetailDialog: (props: unknown) => mockDocumentDetailDialog(props),
}))

jest.mock('@/features/knowledge/document/hooks/useDocuments', () => ({
  useDocuments: () => ({
    create: mockCreateDocument,
  }),
}))

jest.mock('@/features/knowledge/document/utils/document-lookup', () => ({
  findDocumentForDeepLink: (...args: unknown[]) => mockFindDocumentForDeepLink(...args),
}))

jest.mock('@/features/knowledge/multimodal/hooks/useModelSupportsVideo', () => ({
  useModelSupportsVideo: () => true,
}))

jest.mock('@/apis/knowledge', () => ({
  createWebDocument: jest.fn(),
}))

const knowledgeBase: KnowledgeBase = {
  id: 12,
  name: 'organization-kb',
  description: null,
  user_id: 7,
  namespace: 'organization-name',
  document_count: 3,
  is_active: true,
  summary_enabled: false,
  max_calls_per_conversation: 10,
  exempt_calls_before_check: 0,
  created_at: '2026-07-27T00:00:00Z',
  updated_at: '2026-07-27T00:00:00Z',
}

describe('DocumentPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    localStorage.clear()
    mockCreateDocument.mockResolvedValue({ id: 21 })
    mockFindDocumentForDeepLink.mockResolvedValue(undefined)
  })

  it('forwards organization routing context to document preview', () => {
    render(
      <DocumentPanel
        knowledgeBase={knowledgeBase}
        isOrganization
        canManageDocuments
        onCreateCapabilityDraft={jest.fn()}
      />
    )

    expect(mockDocumentDetailDialog).toHaveBeenLastCalledWith(
      expect.objectContaining({
        isOrganization: true,
        knowledgeBaseName: 'organization-kb',
        knowledgeBaseNamespace: 'organization-name',
        canEdit: true,
      })
    )
  })

  it('shows direct source upload only to document editors', () => {
    const { rerender } = render(
      <DocumentPanel knowledgeBase={knowledgeBase} onCreateCapabilityDraft={jest.fn()} />
    )

    expect(screen.queryByTestId('artifact-add-source')).not.toBeInTheDocument()

    rerender(
      <DocumentPanel
        knowledgeBase={knowledgeBase}
        canManageDocuments
        onCreateCapabilityDraft={jest.fn()}
      />
    )
    fireEvent.click(screen.getByTestId('artifact-add-source'))

    expect(screen.getByTestId('mock-table-add')).toBeInTheDocument()
  })

  it('creates quick-added sources in the knowledge base root', async () => {
    render(
      <DocumentPanel
        knowledgeBase={knowledgeBase}
        canManageDocuments
        onCreateCapabilityDraft={jest.fn()}
      />
    )

    fireEvent.click(screen.getByTestId('artifact-add-source'))
    fireEvent.click(screen.getByTestId('mock-table-add'))

    await waitFor(() =>
      expect(mockCreateDocument).toHaveBeenCalledWith({
        name: 'Sales table',
        file_extension: 'table',
        file_size: 0,
        source_type: 'table',
        source_config: { url: 'https://example.com/table' },
        folder_id: 0,
      })
    )
  })

  it('opens a document path directly in the workshop preview', async () => {
    const document = {
      id: 31,
      name: 'guide.md',
    } as KnowledgeDocument
    mockFindDocumentForDeepLink.mockResolvedValue(document)

    render(
      <DocumentPanel
        knowledgeBase={knowledgeBase}
        initialDocPath="guide.md"
        initialDocumentId={31}
        onCreateCapabilityDraft={jest.fn()}
      />
    )

    await waitFor(() =>
      expect(mockDocumentDetailDialog).toHaveBeenLastCalledWith(
        expect.objectContaining({
          document,
        })
      )
    )
    expect(mockFindDocumentForDeepLink).toHaveBeenCalledWith(
      knowledgeBase.id,
      'guide.md',
      31,
      expect.any(AbortSignal)
    )
  })

  it('keeps knowledge sources expanded for browsing', () => {
    render(<DocumentPanel knowledgeBase={knowledgeBase} onCreateCapabilityDraft={jest.fn()} />)

    expect(mockArtifactSourceSelector).toHaveBeenLastCalledWith(
      expect.objectContaining({
        defaultDocumentsExpanded: true,
        purpose: 'workspace',
      })
    )
    expect(screen.getByText('artifact.source')).toBeInTheDocument()
  })

  it('forwards PPT draft creation to the knowledge workspace', () => {
    const onCreateCapabilityDraft = jest.fn()
    render(
      <DocumentPanel
        knowledgeBase={knowledgeBase}
        onCreateCapabilityDraft={onCreateCapabilityDraft}
      />
    )

    fireEvent.click(screen.getByTestId('mock-create-ppt-draft'))

    expect(onCreateCapabilityDraft).toHaveBeenCalledWith('presentation')
  })
})
