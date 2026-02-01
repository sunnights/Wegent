// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/hooks/useTranslation'
import { taskApis, type RestorableTaskError } from '@/apis/tasks'
import { useToast } from '@/hooks/use-toast'

export interface RestoreTaskDialogProps {
  /** Whether the dialog is open */
  open: boolean
  /** Called when the dialog should close */
  onOpenChange: (open: boolean) => void
  /** Restorable task info from the 409 error response */
  restorableInfo: RestorableTaskError | null
  /** The pending message that triggered the restore prompt */
  pendingMessage: string
  /** Called after successful restore with the task ID */
  onRestoreSuccess: (taskId: number) => void
}

/**
 * RestoreTaskDialog Component
 *
 * Displays when a user tries to send a message to an expired task.
 * Allows the user to restore the task and continue the conversation.
 */
export function RestoreTaskDialog({
  open,
  onOpenChange,
  restorableInfo,
  pendingMessage,
  onRestoreSuccess,
}: RestoreTaskDialogProps) {
  const { t } = useTranslation('chat')
  const { toast } = useToast()
  const [isRestoring, setIsRestoring] = useState(false)

  const handleRestore = async () => {
    if (!restorableInfo) return

    setIsRestoring(true)
    try {
      const response = await taskApis.restoreTask(restorableInfo.task_id, {
        prompt: pendingMessage,
      })

      if (response.success) {
        toast({
          title: t('restore.success'),
        })
        onRestoreSuccess(response.task_id)
        onOpenChange(false)
      } else {
        toast({
          variant: 'destructive',
          title: t('restore.failed'),
          description: response.message,
        })
      }
    } catch (error) {
      console.error('[RestoreTaskDialog] Failed to restore task:', error)
      toast({
        variant: 'destructive',
        title: t('restore.failed'),
        description: error instanceof Error ? error.message : undefined,
      })
    } finally {
      setIsRestoring(false)
    }
  }

  const handleCancel = () => {
    onOpenChange(false)
  }

  if (!restorableInfo) return null

  const taskTypeDescription =
    restorableInfo.task_type === 'chat'
      ? t('restore.description_chat')
      : t('restore.description_code')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            </div>
            <DialogTitle>{t('restore.title')}</DialogTitle>
          </div>
          <DialogDescription className="pt-2">
            <span>{taskTypeDescription}</span>
            <br />
            <span className="mt-1 block">{t('restore.description')}</span>
          </DialogDescription>
        </DialogHeader>

        {restorableInfo.executor_deleted && (
          <div className="rounded-md border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200">
            <div className="flex items-start gap-2">
              <RefreshCw className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>{t('restore.executor_rebuilding')}</span>
            </div>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={handleCancel} disabled={isRestoring}>
            {t('restore.cancel')}
          </Button>
          <Button variant="primary" onClick={handleRestore} disabled={isRestoring}>
            {isRestoring ? t('restore.restoring') : t('restore.button')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default RestoreTaskDialog
