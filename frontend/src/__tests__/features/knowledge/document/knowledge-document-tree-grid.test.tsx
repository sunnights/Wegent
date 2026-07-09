// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'

import { KnowledgeDocumentTreeGrid } from '@/features/knowledge/document/components/KnowledgeDocumentTreeGrid'
import type { KnowledgeDocument, KnowledgeFolder } from '@/types/knowledge'

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, number>) =>
      params?.count !== undefined ? `${key}:${params.count}` : key,
  }),
}))

jest.mock('@/apis/attachments', () => ({
  downloadAttachment: jest.fn(),
}))

function createDocument(overrides?: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: 10,
    kind_id: 1,
    user_id: 1,
    name: 'doc.txt',
    file_extension: 'txt',
    file_size: 128,
    status: 'enabled',
    is_active: true,
    index_status: 'success',
    index_generation: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    folder_id: 0,
    source_type: 'file',
    source_config: {},
    attachment_id: null,
    created_by: 'alice',
    ...overrides,
  }
}

function createFolder(overrides?: Partial<KnowledgeFolder>): KnowledgeFolder {
  return {
    id: 1,
    kind_id: 1,
    parent_id: 0,
    name: 'Reports',
    document_count: 1,
    direct_document_count: 1,
    total_document_count: 1,
    children: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderTreeGrid(
  overrides?: Partial<React.ComponentProps<typeof KnowledgeDocumentTreeGrid>>
) {
  const props: React.ComponentProps<typeof KnowledgeDocumentTreeGrid> = {
    folders: [],
    documents: [],
    canManageAllDocuments: true,
    canManageAnyDocuments: true,
    canUpload: true,
    canManage: () => true,
    canSelect: () => true,
    selectedIds: new Set(),
    includedInFolderScope: () => false,
    onSelect: jest.fn(),
    onSelectAll: jest.fn(),
    isAllSelected: false,
    isPartialSelected: false,
    paginationEnabled: false,
    selectedFolderIds: new Set(),
    onSelectFolder: jest.fn(),
    onActivateFolder: jest.fn(),
    onCreateFolder: jest.fn(),
    onRenameFolder: jest.fn(),
    onDeleteFolder: jest.fn(),
    onViewDetail: jest.fn(),
    onEdit: jest.fn(),
    onDelete: jest.fn(),
    onRefresh: jest.fn(),
    onReindex: jest.fn(),
    onMove: jest.fn(),
    sortIcon: () => null,
    onSort: jest.fn(),
    ...overrides,
  }

  return {
    ...render(<KnowledgeDocumentTreeGrid {...props} />),
    props,
  }
}

describe('KnowledgeDocumentTreeGrid', () => {
  it('renders nested folders and documents through the Headless Tree-backed grid', () => {
    const folder = createFolder({
      children: [
        createFolder({
          id: 2,
          parent_id: 1,
          name: 'Child',
          total_document_count: 1,
        }),
      ],
    })

    renderTreeGrid({
      folders: [folder],
      documents: [createDocument({ id: 11, name: 'child-doc.txt', folder_id: 2 })],
    })

    expect(screen.getByText('Reports')).toBeInTheDocument()
    expect(screen.getByText('Child')).toBeInTheDocument()
    expect(screen.getByText('child-doc.txt')).toBeInTheDocument()
  })

  it('routes folder checkbox changes to folder selection without selecting documents directly', () => {
    const onSelectFolder = jest.fn()
    const onSelectDocument = jest.fn()

    renderTreeGrid({
      folders: [createFolder()],
      documents: [createDocument({ id: 11, folder_id: 1 })],
      onSelectFolder,
      onSelect: onSelectDocument,
    })

    fireEvent.click(screen.getByTestId('folder-checkbox-1'))

    expect(onSelectFolder).toHaveBeenCalledWith(1, true)
    expect(onSelectDocument).not.toHaveBeenCalled()
  })

  it('marks child folders covered by a selected ancestor as checked and disabled', () => {
    const folder = createFolder({
      total_document_count: 2,
      children: [
        createFolder({
          id: 2,
          parent_id: 1,
          name: 'Child',
          total_document_count: 1,
        }),
      ],
    })

    renderTreeGrid({
      folders: [folder],
      documents: [createDocument({ id: 11, folder_id: 2 })],
      selectedFolderIds: new Set([1]),
    })

    const childCheckbox = screen.getByTestId('folder-checkbox-2')
    expect(childCheckbox).toBeChecked()
    expect(childCheckbox).toBeDisabled()
  })
})
