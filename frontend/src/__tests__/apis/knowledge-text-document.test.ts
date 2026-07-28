// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { apiClient } from '@/apis/client'
import { createTextKnowledgeDocument } from '@/apis/knowledge'

jest.mock('@/apis/client', () => ({
  apiClient: {
    post: jest.fn(),
  },
}))

describe('createTextKnowledgeDocument', () => {
  it('fixes the document source, format, and root folder', async () => {
    const document = { id: 42 }
    ;(apiClient.post as jest.Mock).mockResolvedValue(document)

    await expect(
      createTextKnowledgeDocument({
        knowledge_base_id: 7,
        name: 'Saved answer',
        content: '# Saved answer',
      })
    ).resolves.toBe(document)

    expect(apiClient.post).toHaveBeenCalledWith('/knowledge/documents', {
      knowledge_base_id: 7,
      name: 'Saved answer',
      content: '# Saved answer',
      source_type: 'text',
      file_extension: 'md',
      folder_id: 0,
    })
  })

  it('forwards structured Markdown origin metadata', async () => {
    ;(apiClient.post as jest.Mock).mockResolvedValue({ id: 43 })

    await createTextKnowledgeDocument({
      knowledge_base_id: 7,
      name: 'Mind map',
      content: '```mermaid\nmindmap\n  root((Topic))\n```',
      content_kind: 'mind_map',
      origin_task_id: 42,
    })

    expect(apiClient.post).toHaveBeenLastCalledWith(
      '/knowledge/documents',
      expect.objectContaining({
        content_kind: 'mind_map',
        origin_task_id: 42,
      })
    )
  })
})
