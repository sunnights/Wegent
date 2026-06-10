// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useCallback, useEffect, useState } from 'react'
import { Cloud, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/hooks/useTranslation'
import { toast } from '@/hooks/use-toast'
import { copyCloudFileToAttachment, listCloudFiles, type CloudFile } from '@/apis/cloud-drive'
import type { Attachment } from '@/types/api'
import { formatFileSize, toAttachment } from './utils'

interface CloudDrivePickerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onAttachmentSelected: (attachment: Attachment) => void
}

export function CloudDrivePicker({
  open,
  onOpenChange,
  onAttachmentSelected,
}: CloudDrivePickerProps) {
  const { t } = useTranslation('cloud-drive')
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<CloudFile[]>([])
  const [loading, setLoading] = useState(false)
  const [copyingId, setCopyingId] = useState<number | null>(null)

  const loadFiles = useCallback(async () => {
    if (!open) return
    setLoading(true)
    try {
      const response = await listCloudFiles({
        query,
        page_size: 20,
        sort: 'created_desc',
      })
      setFiles(response.items.filter(file => file.status === 'ready'))
    } catch {
      toast({ title: t('load_failed'), variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [open, query, t])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles])

  const handleChoose = async (file: CloudFile) => {
    setCopyingId(file.id)
    try {
      const attachment = await copyCloudFileToAttachment(file.id)
      onAttachmentSelected(toAttachment(attachment))
      toast({ title: t('copied') })
      onOpenChange(false)
    } catch {
      toast({ title: t('copy_failed'), variant: 'destructive' })
    } finally {
      setCopyingId(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('picker_title')}</DialogTitle>
          <DialogDescription>{t('picker_description')}</DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <Input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder={t('search_placeholder')}
            className="pl-9"
            data-testid="cloud-drive-picker-search-input"
          />
        </div>

        <div className="max-h-[420px] overflow-y-auto">
          {!loading && files.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted">
              <Cloud className="h-8 w-8" />
              <p className="text-sm">{t('no_ready_file')}</p>
            </div>
          )}
          <div className="divide-y divide-border">
            {files.map(file => (
              <div key={file.id} className="flex items-center gap-3 py-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-surface text-primary">
                  <Cloud className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium" title={file.display_name}>
                    {file.display_name}
                  </div>
                  <div className="text-xs text-text-muted">
                    {formatFileSize(file.file_size)} · {file.file_extension || file.mime_type}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => void handleChoose(file)}
                  disabled={copyingId === file.id}
                  data-testid={`cloud-drive-picker-choose-${file.id}`}
                >
                  {t('actions.choose')}
                </Button>
              </div>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
