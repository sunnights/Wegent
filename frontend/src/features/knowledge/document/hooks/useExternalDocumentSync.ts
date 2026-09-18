// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useCallback, useState } from 'react'

import { synchronizeExternalDocument } from '@/apis/knowledge'
import { toast } from '@/hooks/use-toast'
import { useTranslation } from '@/hooks/useTranslation'
import type { KnowledgeDocument } from '@/types/knowledge'

import { mapKnowledgeDocumentErrorMessage } from '../utils/error-messages'
import { isSyncedWikiDocument } from '../utils/documentUtils'

/**
 * Queue a manual refresh of one imported external document.
 *
 * The knowledge base list and the document detail preview share this entry so
 * both surfaces queue the same request, track their own in-flight state, and
 * report the same failure reason.
 */
export function useExternalDocumentSync() {
  const { t } = useTranslation('knowledge')
  const [syncingDocumentIds, setSyncingDocumentIds] = useState<Set<number>>(() => new Set())

  const isSyncing = useCallback(
    (documentId: number) => syncingDocumentIds.has(documentId),
    [syncingDocumentIds]
  )

  const syncDocument = useCallback(
    async (document: KnowledgeDocument): Promise<boolean> => {
      setSyncingDocumentIds(current => new Set(current).add(document.id))
      const isWikiCopy = isSyncedWikiDocument(document)
      try {
        await synchronizeExternalDocument(document.id)
        toast({
          description: t(
            isWikiCopy ? 'document.document.resyncSuccess' : 'document.document.syncSuccess'
          ),
        })
        return true
      } catch (err) {
        toast({
          variant: 'destructive',
          description: mapKnowledgeDocumentErrorMessage(
            err,
            t,
            isWikiCopy ? 'document.document.resyncFailed' : 'document.document.syncFailed'
          ),
        })
        return false
      } finally {
        setSyncingDocumentIds(current => {
          const next = new Set(current)
          next.delete(document.id)
          return next
        })
      }
    },
    [t]
  )

  return { isSyncing, syncDocument }
}
