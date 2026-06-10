// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

export function formatFileSize(bytes?: number | null): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

export function toAttachment(cloudAttachment: {
  id: number
  filename: string
  file_size: number
  mime_type: string
  status: string
  text_length?: number | null
  error_message?: string | null
  error_code?: string | null
  file_extension?: string
  created_at?: string
}) {
  return {
    id: cloudAttachment.id,
    filename: cloudAttachment.filename,
    file_size: cloudAttachment.file_size,
    mime_type: cloudAttachment.mime_type,
    status: cloudAttachment.status as 'uploading' | 'parsing' | 'ready' | 'failed',
    text_length: cloudAttachment.text_length,
    error_message: cloudAttachment.error_message,
    error_code: cloudAttachment.error_code,
    subtask_id: null,
    file_extension: cloudAttachment.file_extension || '',
    created_at: cloudAttachment.created_at || new Date().toISOString(),
    truncation_info: null,
  }
}
