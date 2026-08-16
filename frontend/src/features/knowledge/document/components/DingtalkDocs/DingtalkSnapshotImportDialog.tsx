// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { listKnowledgeBases } from '@/apis/knowledge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Spinner } from '@/components/ui/spinner'
import { useTranslation } from '@/hooks/useTranslation'
import type { KnowledgeBase } from '@/types/knowledge'

interface DingtalkSnapshotImportDialogProps {
  open: boolean
  selectedCount: number
  isSubmitting: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (knowledgeBaseId: number) => Promise<void>
}

export function DingtalkSnapshotImportDialog({
  open,
  selectedCount,
  isSubmitting,
  onOpenChange,
  onConfirm,
}: DingtalkSnapshotImportDialogProps) {
  const { t } = useTranslation('knowledge')
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [targetId, setTargetId] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (!open) {
      setTargetId('')
      return
    }
    setIsLoading(true)
    listKnowledgeBases('all')
      .then(response => {
        setKnowledgeBases(response.items.filter(kb => kb.kb_type !== 'code_wiki'))
      })
      .catch(() => setKnowledgeBases([]))
      .finally(() => setIsLoading(false))
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="w-5 h-5 text-primary" />
            {t('document.dingtalk.importTitle', '导入到 Wegent 知识库')}
          </DialogTitle>
          <DialogDescription>
            {t('document.dingtalk.importHint', '将选中的 {{count}} 项复制为静态快照。', {
              count: selectedCount,
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-1.5">
            <Label>{t('document.dingtalk.targetKnowledgeBase', '目标知识库')}</Label>
            {isLoading ? (
              <div className="flex justify-center py-3">
                <Spinner />
              </div>
            ) : (
              <Select value={targetId} onValueChange={setTargetId}>
                <SelectTrigger data-testid="dingtalk-import-target-kb-select">
                  <SelectValue
                    placeholder={t('document.dingtalk.selectKnowledgeBase', '请选择知识库')}
                  />
                </SelectTrigger>
                <SelectContent>
                  {knowledgeBases.map(kb => (
                    <SelectItem key={kb.id} value={String(kb.id)}>
                      {kb.namespace === 'default' ? kb.name : `${kb.namespace} / ${kb.name}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {!isLoading && knowledgeBases.length === 0 && (
              <p className="text-sm text-text-muted">
                {t('document.dingtalk.noTargetKnowledgeBase', '暂无可用知识库。')}{' '}
                <Link href="/knowledge" className="text-primary hover:underline">
                  {t('document.dingtalk.createKnowledgeBase', '创建知识库')}
                </Link>
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            data-testid="dingtalk-import-cancel-button"
          >
            {t('common:actions.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={() => onConfirm(Number(targetId))}
            disabled={!targetId || isSubmitting || isLoading}
            data-testid="dingtalk-import-confirm-button"
          >
            {isSubmitting
              ? t('document.dingtalk.importing', '导入中...')
              : t('document.dingtalk.import', '导入')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
