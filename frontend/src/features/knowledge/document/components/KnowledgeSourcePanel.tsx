// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Search, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Spinner } from '@/components/ui/spinner'
import { useTranslation } from '@/hooks/useTranslation'
import type { KnowledgeBase, KnowledgeDocument, SplitterConfig } from '@/types/knowledge'
import { useModelSupportsVideo } from '@/features/knowledge/multimodal/hooks/useModelSupportsVideo'
import { createWebDocument } from '@/apis/knowledge'
import { DocumentDetailDialog } from './DocumentDetailDialog'
import { DocumentItem } from './DocumentItem'
import { DocumentUpload, type TableDocument } from './DocumentUpload'
import { WorkspaceSidePanel } from './WorkspaceSidePanel'
import { useDocuments } from '../hooks/useDocuments'
import { createDocumentsFromAttachments } from '../utils/document-creation'
import { findDocumentForDeepLink } from '../utils/document-lookup'

interface KnowledgeSourcePanelProps {
  knowledgeBase: KnowledgeBase
  selectedDocumentIds: number[]
  availableDocumentCount: number | null
  processingDocumentCount: number
  canManageArtifacts: boolean | null
  canManageDocuments: boolean
  mobileVisible: boolean
  refreshToken: number
  isOrganization?: boolean
  initialDocPath?: string
  initialDocumentId?: number
  onDocumentSelectionChange: (documentIds: number[]) => void
  onSourcesChanged: () => void
}

export function KnowledgeSourcePanel({
  knowledgeBase,
  selectedDocumentIds,
  availableDocumentCount,
  processingDocumentCount,
  canManageArtifacts,
  canManageDocuments,
  mobileVisible,
  refreshToken,
  isOrganization = false,
  initialDocPath,
  initialDocumentId,
  onDocumentSelectionChange,
  onSourcesChanged,
}: KnowledgeSourcePanelProps) {
  const { t } = useTranslation('knowledge')
  const [viewingDocument, setViewingDocument] = useState<KnowledgeDocument | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const previousRefreshTokenRef = useRef(refreshToken)
  const modelSupportsVideo = useModelSupportsVideo(knowledgeBase)
  const {
    documents,
    loading,
    error,
    create: createDocument,
    refresh,
    page,
    pageSize,
    totalCount,
    totalPages,
    goToPage,
  } = useDocuments({
    knowledgeBaseId: knowledgeBase.id,
    paginationEnabled: true,
    serverPaginationOnly: true,
    initialPageSize: 20,
    keyword: searchQuery,
    sortBy: 'name',
    sortOrder: 'asc',
  })
  const selectedDocumentIdSet = new Set(selectedDocumentIds)
  const ragConfigured = !!(
    knowledgeBase.retrieval_config?.retriever_name &&
    knowledgeBase.retrieval_config?.embedding_config?.model_name
  )

  const handleDocumentSelection = (document: KnowledgeDocument, checked: boolean) => {
    const next = new Set(selectedDocumentIds)
    if (checked) next.add(document.id)
    else next.delete(document.id)
    onDocumentSelectionChange(Array.from(next))
  }

  const handleUploadComplete = async (
    attachments: Parameters<typeof createDocumentsFromAttachments>[0]['attachments'],
    splitterConfig?: Partial<SplitterConfig>,
    multimodalAnalysisPrompts?: {
      video?: string | null
      image?: string | null
    }
  ) => {
    const results = await createDocumentsFromAttachments({
      attachments,
      folderId: 0,
      splitterConfig,
      multimodalAnalysisPrompts,
      createDocument,
      fallbackError: t('document.document.createFailed'),
    })
    if (results.some(result => result.documentId !== undefined)) onSourcesChanged()
    return results
  }

  const handleTableAdd = async (data: TableDocument) => {
    await createDocument({
      name: data.name,
      file_extension: 'table',
      file_size: 0,
      source_type: 'table',
      source_config: data.source_config,
      folder_id: 0,
    })
    setUploadOpen(false)
    onSourcesChanged()
  }

  const handleWebAdd = async (url: string, name?: string) => {
    const result = await createWebDocument(url, knowledgeBase.id, name, 0)
    if (!result.success) {
      throw new Error(result.error_message || t('document.document.createFailed'))
    }
    setUploadOpen(false)
    onSourcesChanged()
  }

  useEffect(() => {
    if (!initialDocPath) return

    const controller = new AbortController()
    void findDocumentForDeepLink(
      knowledgeBase.id,
      initialDocPath,
      initialDocumentId,
      controller.signal
    )
      .then(document => {
        if (!controller.signal.aborted && document) {
          setViewingDocument(document)
        }
      })
      .catch(() => {
        // Document auto-open is best-effort.
      })

    return () => controller.abort()
  }, [initialDocPath, initialDocumentId, knowledgeBase.id])

  useEffect(() => {
    if (previousRefreshTokenRef.current === refreshToken) return
    previousRefreshTokenRef.current = refreshToken
    void refresh()
  }, [refresh, refreshToken])

  useEffect(() => {
    const handleFocus = () => void refresh()
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [refresh])

  useEffect(() => {
    if (processingDocumentCount <= 0) return
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(timer)
  }, [processingDocumentCount, refresh])

  return (
    <WorkspaceSidePanel
      side="left"
      storageKey="kb-source-panel"
      defaultWidth={300}
      minWidth={240}
      maxWidth={420}
      mobileVisible={mobileVisible}
      expandLabel={t('artifact.showSources')}
      collapseLabel={t('artifact.hideSources')}
      resizeLabel={t('artifact.resizeSources')}
      expandTestId="knowledge-source-panel-expand-button"
      collapseTestId="knowledge-source-panel-collapse-button"
    >
      <div className="flex min-h-0 flex-1 flex-col p-4" data-testid="knowledge-source-panel">
        <div className="mb-3 flex min-h-8 items-center justify-between gap-2 pr-9">
          <h2 className="text-sm font-semibold">
            {t(
              canManageArtifacts === false ? 'artifact.sourceBrowser.documents' : 'artifact.source'
            )}
          </h2>
          {canManageDocuments && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-2.5 text-xs"
              onClick={() => setUploadOpen(true)}
              data-testid="artifact-add-source"
            >
              <Upload className="mr-1.5 h-4 w-4" />
              {t('document.document.upload')}
            </Button>
          )}
        </div>

        <div className="mb-3 flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <Input
              value={searchQuery}
              onChange={event => setSearchQuery(event.target.value)}
              placeholder={t('artifact.sourceDialog.search')}
              className="h-9 pl-9"
              data-testid="knowledge-source-search"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-9 w-9 shrink-0 p-0"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label={t('common:actions.refresh')}
            data-testid="knowledge-source-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>

        <div className="mb-2 flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-text-muted">
          <span>
            {selectedDocumentIds.length > 0
              ? t('artifact.sourceDialog.selectedHint', {
                  count: selectedDocumentIds.length,
                })
              : t('artifact.sourceDialog.allHint', {
                  count: availableDocumentCount ?? knowledgeBase.document_count,
                })}
          </span>
          {selectedDocumentIds.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 px-2 text-xs"
              onClick={() => onDocumentSelectionChange([])}
              data-testid="knowledge-source-clear"
            >
              {t('artifact.sourceDialog.clear')}
            </Button>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {loading && documents.length === 0 ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : error && documents.length === 0 ? (
            <div className="flex flex-col items-center py-12 text-center">
              <p className="text-sm text-error">{error}</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => void refresh()}>
                {t('common:actions.retry')}
              </Button>
            </div>
          ) : documents.length === 0 ? (
            <p className="py-12 text-center text-sm text-text-secondary">
              {t('artifact.sourceDialog.empty')}
            </p>
          ) : (
            <div className="space-y-2">
              {documents.map(document => {
                const selected = selectedDocumentIdSet.has(document.id)
                const canSelect =
                  selected || (document.is_active && document.index_status === 'success')
                return (
                  <DocumentItem
                    key={document.id}
                    document={document}
                    compact
                    canManage={false}
                    canSelect={canSelect}
                    selected={selected}
                    onSelect={canSelect ? handleDocumentSelection : undefined}
                    onViewDetail={setViewingDocument}
                    ragConfigured={ragConfigured}
                  />
                )
              })}
            </div>
          )}
        </div>

        {totalCount > pageSize && (
          <Pagination
            page={page}
            totalPages={totalPages}
            totalCount={totalCount}
            pageSize={pageSize}
            onGoToPage={goToPage}
            showPageSizeSelector={false}
            disabled={loading}
          />
        )}
      </div>

      <DocumentDetailDialog
        open={!!viewingDocument}
        onOpenChange={open => !open && setViewingDocument(null)}
        document={viewingDocument}
        knowledgeBaseId={knowledgeBase.id}
        kbType={knowledgeBase.kb_type}
        canEdit={canManageDocuments}
        knowledgeBaseName={knowledgeBase.name}
        knowledgeBaseNamespace={knowledgeBase.namespace || 'default'}
        isOrganization={isOrganization}
      />

      <DocumentUpload
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        onUploadComplete={handleUploadComplete}
        onTableAdd={handleTableAdd}
        onWebAdd={handleWebAdd}
        folderId={0}
        multimodalAnalysisEnabled={knowledgeBase.multimodal_analysis_enabled}
        multimodalModelSupportsVideo={modelSupportsVideo}
        multimodalVideoPrompt={knowledgeBase.multimodal_analysis_video_prompt}
        multimodalImagePrompt={knowledgeBase.multimodal_analysis_image_prompt}
      />
    </WorkspaceSidePanel>
  )
}
