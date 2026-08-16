// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DingtalkDocsPage } from '@/features/knowledge/document/components/DingtalkDocs/DingtalkDocsPage'

const mockPush = jest.fn()
const mockGetSyncStatus = jest.fn()
const mockGetWikispaceSyncStatus = jest.fn()
const mockGetDocs = jest.fn()
const mockImportSnapshot = jest.fn()
const mockListKnowledgeBases = jest.fn()

const mockT = (key: string, fallback?: string) => fallback ?? key

jest.mock('@/hooks/useTranslation', () => ({
  useTranslation: () => ({ t: mockT }),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

jest.mock('@/apis/dingtalk-doc', () => ({
  dingtalkDocApi: {
    getSyncStatus: (...args: unknown[]) => mockGetSyncStatus(...args),
    getWikispaceSyncStatus: (...args: unknown[]) => mockGetWikispaceSyncStatus(...args),
    getDocs: (...args: unknown[]) => mockGetDocs(...args),
    getWikispaceNodes: jest.fn(),
    syncDocs: jest.fn(),
    syncWikispaceNodes: jest.fn(),
    importSnapshot: (...args: unknown[]) => mockImportSnapshot(...args),
  },
}))

jest.mock('@/apis/knowledge', () => ({
  listKnowledgeBases: (...args: unknown[]) => mockListKnowledgeBases(...args),
}))

jest.mock('@/hooks/use-toast', () => ({
  toast: jest.fn(),
}))

describe('DingtalkDocsPage MCP readiness', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockGetSyncStatus.mockResolvedValue({
      is_configured: false,
      last_synced_at: null,
      total_nodes: 0,
    })
    mockGetWikispaceSyncStatus.mockResolvedValue({
      is_configured: false,
      last_synced_at: null,
      total_nodes: 0,
    })
    mockGetDocs.mockResolvedValue({ nodes: [], total_count: 0 })
    mockListKnowledgeBases.mockResolvedValue({ items: [] })
  })

  it('keeps both tabs reachable when neither readiness flag is true', async () => {
    const user = userEvent.setup()
    render(<DingtalkDocsPage isConfigured={false} isWikispaceConfigured={false} />)

    expect(screen.getByTestId('dingtalk-docs-page')).toBeInTheDocument()
    expect(screen.getByTestId('dingtalk-not-configured')).toHaveTextContent('未配置钉钉文档')

    await user.click(screen.getByTestId('dingtalk-tab-wikispace'))

    expect(screen.getByText('同步需要同时配置钉钉知识库 MCP 和钉钉文档 MCP')).toBeInTheDocument()
  })

  it('keeps Docs usable when only WikiSpace sync is not ready', async () => {
    const user = userEvent.setup()
    mockGetSyncStatus.mockResolvedValue({
      is_configured: true,
      last_synced_at: null,
      total_nodes: 0,
    })
    render(<DingtalkDocsPage isConfigured={true} isWikispaceConfigured={false} />)

    expect(screen.getByTestId('dingtalk-sync-button')).toBeEnabled()

    await user.click(screen.getByTestId('dingtalk-tab-wikispace'))

    expect(screen.getByTestId('dingtalk-sync-button')).toBeDisabled()
    expect(screen.getByText('同步需要同时配置钉钉知识库 MCP 和钉钉文档 MCP')).toBeInTheDocument()
  })

  it('imports a selected DingTalk document into the chosen Wegent KB', async () => {
    const user = userEvent.setup()
    mockGetSyncStatus.mockResolvedValue({
      is_configured: true,
      last_synced_at: null,
      total_nodes: 1,
    })
    mockGetDocs.mockResolvedValue({
      total_count: 1,
      nodes: [
        {
          id: 3,
          dingtalk_node_id: 'doc-3',
          name: 'Design',
          doc_url: 'https://alidocs.dingtalk.com/i/nodes/doc-3',
          parent_node_id: '',
          node_type: 'doc',
          workspace_id: '',
          content_type: 'ALIDOC',
          content_updated_at: '2026-08-16T00:00:00Z',
          source: 'docs',
          is_active: true,
          last_synced_at: '2026-08-16T00:00:00Z',
          created_at: '2026-08-16T00:00:00Z',
          updated_at: '2026-08-16T00:00:00Z',
        },
      ],
    })
    mockListKnowledgeBases.mockResolvedValue({
      items: [{ id: 8, name: 'Agent KB', namespace: 'default', kb_type: 'classic' }],
    })
    mockImportSnapshot.mockResolvedValue({
      task_id: 'task-1',
      knowledge_base_id: 8,
      selected_count: 1,
    })

    render(<DingtalkDocsPage isConfigured={true} />)

    await user.click(await screen.findByTestId('dingtalk-select-node-3'))
    await user.click(screen.getByTestId('dingtalk-import-button'))
    await user.click(await screen.findByTestId('dingtalk-import-target-kb-select'))
    await user.click(await screen.findByText('Agent KB'))
    await user.click(screen.getByTestId('dingtalk-import-confirm-button'))

    await waitFor(() => expect(mockImportSnapshot).toHaveBeenCalledWith(8, [3]))
  })
})
