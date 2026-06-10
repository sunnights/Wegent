// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Cloud, Download, Eye, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import TopNavigation from '@/features/layout/TopNavigation'
import { DesktopNavLinks } from '@/features/layout/components/DesktopNavLinks'
import { MobileNavTabs } from '@/features/layout/components/MobileNavTabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useIsMobile } from '@/features/layout/hooks/useMediaQuery'
import { useTranslation } from '@/hooks/useTranslation'
import { toast } from '@/hooks/use-toast'
import { getAttachmentPreviewUrl } from '@/apis/attachments'
import {
  deleteCloudFile,
  getCloudDriveStats,
  listCloudFiles,
  uploadCloudFile,
  type CloudFile,
  type CloudFileStatsResponse,
} from '@/apis/cloud-drive'
import { formatFileSize } from './utils'

const FILE_TYPES = [
  'all',
  'image',
  'document',
  'spreadsheet',
  'presentation',
  'pdf',
  'text',
  'video',
  'audio',
  'other',
]
const SORTS = ['created_desc', 'created_asc', 'name_asc', 'name_desc', 'size_asc', 'size_desc']

export function CloudDrivePage() {
  const { t } = useTranslation('cloud-drive')
  const isMobile = useIsMobile()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<CloudFile[]>([])
  const [stats, setStats] = useState<CloudFileStatsResponse>({ total_count: 0, total_size: 0 })
  const [query, setQuery] = useState('')
  const [fileType, setFileType] = useState('all')
  const [sort, setSort] = useState('created_desc')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [listResponse, statsResponse] = await Promise.all([
        listCloudFiles({ query, file_type: fileType, sort, page_size: 100 }),
        getCloudDriveStats(),
      ])
      setFiles(listResponse.items)
      setStats(statsResponse)
    } catch {
      toast({ title: t('load_failed'), variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [fileType, query, sort, t])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await uploadCloudFile(file)
      toast({ title: t('uploaded') })
      await loadData()
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  const handleDelete = async (file: CloudFile) => {
    if (!window.confirm(t('delete_confirm'))) return
    await deleteCloudFile(file.id)
    toast({ title: t('deleted') })
    await loadData()
  }

  const nav = isMobile ? (
    <MobileNavTabs activePage="cloudDrive" />
  ) : (
    <DesktopNavLinks activePage="cloudDrive" />
  )

  return (
    <div className="min-h-screen bg-base text-text-primary">
      <TopNavigation activePage="cloudDrive" variant="standalone" showLogo>
        {nav}
      </TopNavigation>

      <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-4 sm:px-6">
        <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold">{t('title')}</h1>
            <p className="mt-1 text-sm text-text-muted">
              {t('total_files', { count: stats.total_count })} ·{' '}
              {t('total_size', { size: formatFileSize(stats.total_size) })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void loadData()}
              disabled={loading}
              data-testid="cloud-drive-refresh-button"
            >
              <RefreshCw className="h-4 w-4" />
              {t('refresh')}
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              data-testid="cloud-drive-upload-button"
            >
              <Upload className="h-4 w-4" />
              {t('upload')}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={event => void handleUpload(event)}
              data-testid="cloud-drive-upload-input"
            />
          </div>
        </section>

        <section className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <Input
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={t('search_placeholder')}
              className="pl-9"
              data-testid="cloud-drive-search-input"
            />
          </div>
          <Select value={fileType} onValueChange={setFileType}>
            <SelectTrigger className="w-full sm:w-48" data-testid="cloud-drive-type-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FILE_TYPES.map(type => (
                <SelectItem key={type} value={type}>
                  {t(`filters.${type}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={setSort}>
            <SelectTrigger className="w-full sm:w-48" data-testid="cloud-drive-sort-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map(item => (
                <SelectItem key={item} value={item}>
                  {t(`sort.${item}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>

        <section className="overflow-hidden rounded-lg border border-border bg-base">
          {files.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center gap-2 py-20 text-center">
              <Cloud className="h-10 w-10 text-primary" />
              <h2 className="text-lg font-semibold">{t('empty')}</h2>
              <p className="max-w-md text-sm text-text-muted">{t('empty_hint')}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-border bg-surface text-xs text-text-muted">
                  <tr>
                    <th className="px-4 py-3 text-left">{t('columns.name')}</th>
                    <th className="px-4 py-3 text-left">{t('columns.type')}</th>
                    <th className="px-4 py-3 text-left">{t('columns.size')}</th>
                    <th className="px-4 py-3 text-left">{t('columns.source')}</th>
                    <th className="px-4 py-3 text-left">{t('columns.created')}</th>
                    <th className="px-4 py-3 text-right">{t('columns.actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {files.map(file => (
                    <tr key={file.id} className="hover:bg-surface/60">
                      <td className="max-w-[280px] px-4 py-3">
                        <div className="truncate font-medium" title={file.display_name}>
                          {file.display_name}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-text-muted">
                        {file.file_extension || file.mime_type || '-'}
                      </td>
                      <td className="px-4 py-3 text-text-muted">
                        {formatFileSize(file.file_size)}
                      </td>
                      <td className="px-4 py-3 text-text-muted">
                        {t(`source.${file.source_type}`, file.source_type)}
                      </td>
                      <td className="px-4 py-3 text-text-muted">
                        {new Date(file.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" asChild title={t('actions.preview')}>
                            <a
                              href={getAttachmentPreviewUrl(file.attachment_id)}
                              target="_blank"
                              rel="noreferrer"
                              data-testid={`cloud-drive-preview-${file.id}`}
                            >
                              <Eye className="h-4 w-4" />
                            </a>
                          </Button>
                          <Button variant="ghost" size="icon" asChild title={t('actions.download')}>
                            <a
                              href={getAttachmentPreviewUrl(file.attachment_id)}
                              download
                              data-testid={`cloud-drive-download-${file.id}`}
                            >
                              <Download className="h-4 w-4" />
                            </a>
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t('actions.delete')}
                            onClick={() => void handleDelete(file)}
                            data-testid={`cloud-drive-delete-${file.id}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
