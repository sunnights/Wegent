// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeSourcePanel } from '@/features/knowledge/document/components/KnowledgeSourcePanel'
import type { ArtifactSourceScope } from '@/features/knowledge/artifact/components/ArtifactSourceSelector'
import type { KnowledgeBase, KnowledgeDocument } from '@/types/knowledge'

const mockDocumentDetailDialog = jest.fn((_props: unknown) => null)
const mockArtifactSourceSelector = jest.fn()
const mockCreateDocument = jest.fn()
const mockFindDocumentForDeepLink = jest.fn()

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

jest.mock('@/features/knowledge/document/components/WorkspaceSidePanel', () => ({
  WorkspaceSidePanel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

jest.mock('@/features/knowledge/artifact/components/ArtifactSourceSelector', () => ({
  ArtifactSourceSelector: (props: { onScopeChange: (scope: ArtifactSourceScope) => void }) => {
    mockArtifactSourceSelector(props)
    return (
      <button
        data-testid="mock-select-source"
        onClick={() =>
          props.onScopeChange({
            mode: 'selected',
            documentIds: new Set([11]),
          })
        }
      />
    )
  },
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

const defaultProps = {
  knowledgeBase,
  selectedDocumentIds: [] as number[],
  availableDocumentCount: 3,
  processingDocumentCount: 0,
  canManageArtifacts: true,
  canManageDocuments: false,
  mobileVisible: true,
  refreshToken: 0,
  onDocumentSelectionChange: jest.fn(),
  onSourcesChanged: jest.fn(),
}

describe('KnowledgeSourcePanel', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockCreateDocument.mockResolvedValue({ id: 21 })
    mockFindDocumentForDeepLink.mockResolvedValue(undefined)
  })

  it('forwards organization routing context to document preview', () => {
    render(<KnowledgeSourcePanel {...defaultProps} isOrganization canManageDocuments />)

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
    const { rerender } = render(<KnowledgeSourcePanel {...defaultProps} />)

    expect(screen.queryByTestId('artifact-add-source')).not.toBeInTheDocument()

    rerender(<KnowledgeSourcePanel {...defaultProps} canManageDocuments />)
    fireEvent.click(screen.getByTestId('artifact-add-source'))

    expect(screen.getByTestId('mock-table-add')).toBeInTheDocument()
  })

  it('creates quick-added sources in the knowledge base root and refreshes both side panels', async () => {
    const onSourcesChanged = jest.fn()
    render(
      <KnowledgeSourcePanel
        {...defaultProps}
        canManageDocuments
        onSourcesChanged={onSourcesChanged}
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
    expect(onSourcesChanged).toHaveBeenCalledTimes(1)
  })

  it('opens a document path directly in the source preview', async () => {
    const document = {
      id: 31,
      name: 'guide.md',
    } as KnowledgeDocument
    mockFindDocumentForDeepLink.mockResolvedValue(document)

    render(
      <KnowledgeSourcePanel {...defaultProps} initialDocPath="guide.md" initialDocumentId={31} />
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

  it('keeps the source list expanded and reports one shared source scope', () => {
    const onDocumentSelectionChange = jest.fn()
    render(
      <KnowledgeSourcePanel
        {...defaultProps}
        selectedDocumentIds={[7]}
        onDocumentSelectionChange={onDocumentSelectionChange}
      />
    )

    expect(mockArtifactSourceSelector).toHaveBeenLastCalledWith(
      expect.objectContaining({
        defaultDocumentsExpanded: true,
        purpose: 'workspace',
        scope: {
          mode: 'selected',
          documentIds: new Set([7]),
        },
      })
    )

    fireEvent.click(screen.getByTestId('mock-select-source'))
    expect(onDocumentSelectionChange).toHaveBeenCalledWith([11])
  })
})
