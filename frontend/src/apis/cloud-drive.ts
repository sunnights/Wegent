// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { getToken } from './user'
import type { AttachmentResponse } from './attachments'

const API_BASE_URL = ''

export interface CloudFile {
  id: number
  user_id: number
  attachment_id: number
  display_name: string
  file_extension: string
  mime_type: string
  file_size: number
  source_type: string
  source_ref: Record<string, unknown>
  status: string
  text_length: number
  created_at: string
  updated_at?: string | null
}

export interface CloudFileListResponse {
  items: CloudFile[]
  total: number
  page: number
  page_size: number
}

export interface CloudFileStatsResponse {
  total_count: number
  total_size: number
}

export interface CloudFileImportItem {
  cloud_file_id: number
  status: 'success' | 'failed'
  document_id?: number | null
  attachment_id?: number | null
  error?: string | null
}

export interface CloudFileImportToKnowledgeResponse {
  success_count: number
  failed_count: number
  items: CloudFileImportItem[]
}

export interface ListCloudFilesParams {
  page?: number
  page_size?: number
  query?: string
  source_type?: string
  file_type?: string
  sort?: string
}

function authHeaders(): HeadersInit {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text()
    try {
      const json = JSON.parse(text)
      throw new Error(json.detail || text || 'Request failed')
    } catch {
      throw new Error(text || 'Request failed')
    }
  }
  if (response.status === 204) {
    return null as T
  }
  return response.json()
}

export async function listCloudFiles(
  params: ListCloudFilesParams = {}
): Promise<CloudFileListResponse> {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const response = await fetch(`${API_BASE_URL}/api/cloud-drive/files?${search.toString()}`, {
    headers: authHeaders(),
  })
  return parseResponse<CloudFileListResponse>(response)
}

export async function getCloudDriveStats(): Promise<CloudFileStatsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/cloud-drive/stats`, {
    headers: authHeaders(),
  })
  return parseResponse<CloudFileStatsResponse>(response)
}

export async function uploadCloudFile(file: File): Promise<AttachmentResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE_URL}/api/cloud-drive/files/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  return parseResponse<AttachmentResponse>(response)
}

export async function copyCloudFileToAttachment(fileId: number): Promise<AttachmentResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/cloud-drive/files/${fileId}/copy-to-attachment`,
    {
      method: 'POST',
      headers: authHeaders(),
    }
  )
  return parseResponse<AttachmentResponse>(response)
}

export async function deleteCloudFile(fileId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/cloud-drive/files/${fileId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  await parseResponse<void>(response)
}

export async function importCloudFilesToKnowledge(params: {
  knowledge_base_id: number
  file_ids: number[]
  folder_id?: number
  splitter_config?: Record<string, unknown>
}): Promise<CloudFileImportToKnowledgeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/cloud-drive/files/import-to-knowledge`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify(params),
  })
  return parseResponse<CloudFileImportToKnowledgeResponse>(response)
}
