// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useEffect, useState } from 'react'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/hooks/useTranslation'
import type { KnowledgeBase, KnowledgeDocument, SplitterConfig } from '@/types/knowledge'
import {
  ArtifactSourceSelector,
  type ArtifactSourceScope,
} from '@/features/knowledge/artifact/components/ArtifactSourceSelector'
import { useModelSupportsVideo } from '@/features/knowledge/multimodal/hooks/useModelSupportsVideo'
import { createWebDocument } from '@/apis/knowledge'
import { DocumentDetailDialog } from './DocumentDetailDialog'
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
  const modelSupportsVideo = useModelSupportsVideo(knowledgeBase)
  const { create: createDocument } = useDocuments({
    knowledgeBaseId: knowledgeBase.id,
    autoLoad: false,
    paginationEnabled: false,
  })
  const sourceScope: ArtifactSourceScope =
    selectedDocumentIds.length > 0
      ? { mode: 'selected', documentIds: new Set(selectedDocumentIds) }
      : { mode: 'all' }

  const handleSourceScopeChange = (scope: ArtifactSourceScope) => {
    onDocumentSelectionChange(scope.mode === 'all' ? [] : Array.from(scope.documentIds))
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
      <div
        className="flex min-h-0 flex-1 flex-col overflow-auto p-4"
        data-testid="knowledge-source-panel"
      >
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
        <ArtifactSourceSelector
          knowledgeBaseId={knowledgeBase.id}
          scope={sourceScope}
          availableDocumentCount={availableDocumentCount ?? knowledgeBase.document_count}
          processingDocumentCount={processingDocumentCount}
          compact
          purpose={canManageArtifacts === false ? 'question' : 'workspace'}
          defaultDocumentsExpanded
          refreshToken={refreshToken}
          onScopeChange={handleSourceScopeChange}
          onOpenDocument={setViewingDocument}
        />
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
