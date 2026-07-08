// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import {
  Tree,
  type NodeApi,
  type TreeApi,
  type RowRendererProps,
  type NodeRendererProps,
} from 'react-arborist'
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FolderPlus,
  Pencil,
  Trash2,
} from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { DocumentItem } from './DocumentItem'
import type { KnowledgeDocument, KnowledgeFolder } from '@/types/knowledge'
import { useTranslation } from '@/hooks/useTranslation'

/** A node in the document browser: real folder or current document result */
interface FolderNode {
  type: 'api-folder'
  id: number
  name: string
  path: string
  children: TreeNode[]
  documentCount: number
  created_at?: string
  updated_at?: string
}

interface DocumentNode {
  type: 'document'
  displayName: string
  document: KnowledgeDocument
}

type TreeNode = FolderNode | DocumentNode

interface FolderTreeProps {
  /** API folders from knowledge base */
  folders: KnowledgeFolder[]
  /** All documents in the knowledge base */
  documents: KnowledgeDocument[]
  compact?: boolean
  withBorder?: boolean
  onViewDetail?: (doc: KnowledgeDocument) => void
  onEdit?: (doc: KnowledgeDocument) => void
  onDelete?: (doc: KnowledgeDocument) => void
  onRefresh?: (doc: KnowledgeDocument) => void
  onReindex?: (doc: KnowledgeDocument) => void
  onMove?: (doc: KnowledgeDocument) => void
  refreshingDocId?: number | null
  reindexingDocId?: number | null
  canManage?: (doc: KnowledgeDocument) => boolean
  canSelect?: (doc: KnowledgeDocument) => boolean
  selectedIds?: Set<number>
  includedInFolderScope?: (doc: KnowledgeDocument) => boolean
  onSelect?: (doc: KnowledgeDocument, selected: boolean) => void
  ragConfigured?: boolean
  nameColumnWidth?: number
  showActionsColumn?: boolean
  /** Folder CRUD handlers */
  onCreateFolder?: (parentId: number) => void
  onRenameFolder?: (folderId: number, currentName: string) => void
  onDeleteFolder?: (folderId: number, folderName: string) => void
  /** Whether the user can manage folders (permission from KB) */
  canManageFolders?: boolean
  /** Whether folders can be selected for batch operations (e.g., transfer) */
  canSelectFolders?: boolean
  /** Set of selected folder IDs (only API folders with isApiFolder=true) */
  selectedFolderIds?: Set<number>
  /** Callback when a folder is selected or deselected */
  onSelectFolder?: (folderId: number, selected: boolean) => void
  activeFolderId?: number
  onActivateFolder?: (folderId: number) => void
}

export type SortField = 'name' | 'size' | 'createdAt' | 'updatedAt'
export type SortOrder = 'asc' | 'desc'

function toDocumentNode(doc: KnowledgeDocument): DocumentNode {
  return {
    type: 'document',
    displayName: doc.name,
    document: doc,
  }
}

/** Convert API folder nodes to visible nodes and attach current query results by folder_id. */
function convertFolderToNode(
  folder: KnowledgeFolder,
  documentsByFolderId: Map<number, KnowledgeDocument[]>
): FolderNode {
  const childFolderNodes = folder.children.map(child =>
    convertFolderToNode(child, documentsByFolderId)
  )
  const directDocumentNodes = (documentsByFolderId.get(folder.id) ?? []).map(toDocumentNode)

  return {
    type: 'api-folder',
    id: folder.id,
    name: folder.name,
    path: `folder:${folder.id}`,
    children: [...childFolderNodes, ...directDocumentNodes],
    documentCount: folder.total_document_count ?? folder.document_count,
    created_at: folder.created_at,
    updated_at: folder.updated_at,
  }
}

/**
 * Build the visible tree from stable API folders and current document results.
 * Legacy "/" splitting is intentionally not used; "/" remains part of the file name.
 */
function buildMergedTree(folders: KnowledgeFolder[], documents: KnowledgeDocument[]): TreeNode[] {
  const documentsByFolderId = new Map<number, KnowledgeDocument[]>()
  for (const doc of documents) {
    const folderId = doc.folder_id ?? 0
    documentsByFolderId.set(folderId, [...(documentsByFolderId.get(folderId) ?? []), doc])
  }

  const folderNodes = folders.map(folder => convertFolderToNode(folder, documentsByFolderId))
  const knownFolderIds = new Set<number>()
  const collectFolderIds = (items: KnowledgeFolder[]) => {
    for (const folder of items) {
      knownFolderIds.add(folder.id)
      collectFolderIds(folder.children)
    }
  }
  collectFolderIds(folders)

  const rootDocuments = (documentsByFolderId.get(0) ?? []).map(toDocumentNode)
  const orphanDocuments = documents
    .filter(doc => doc.folder_id !== 0 && !knownFolderIds.has(doc.folder_id))
    .map(toDocumentNode)

  return [...folderNodes, ...rootDocuments, ...orphanDocuments]
}

function findFolderPathIds(
  folders: KnowledgeFolder[],
  targetId: number | undefined,
  path: number[] = []
): number[] {
  if (targetId === undefined) return []
  for (const folder of folders) {
    const nextPath = [...path, folder.id]
    if (folder.id === targetId) {
      return nextPath
    }
    const childPath = findFolderPathIds(folder.children, targetId, nextPath)
    if (childPath.length > 0) {
      return childPath
    }
  }
  return []
}

/** Generate a stable key for a tree node based on its type */
function treeNodeKey(node: TreeNode): string {
  if (node.type === 'document') {
    return `doc:${(node as DocumentNode).document.id}`
  }
  return node.path
}

interface FolderRowProps {
  node: FolderNode
  depth: number
  compact: boolean
  expanded: boolean
  onToggle: (path: string) => void
  onCreateFolder?: (parentId: number) => void
  onRenameFolder?: (folderId: number, currentName: string) => void
  onDeleteFolder?: (folderId: number, folderName: string) => void
  canManageFolders?: boolean
  /** Folder selection props */
  canSelectFolders?: boolean
  folderChecked?: boolean | 'indeterminate'
  folderSelectionDisabled?: boolean
  onFolderCheck?: (checked: boolean) => void
  active?: boolean
  onActivate?: (folderId: number) => void
}

function FolderRow({
  node,
  depth,
  compact,
  expanded,
  onToggle,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  canManageFolders,
  canSelectFolders,
  folderChecked,
  folderSelectionDisabled,
  onFolderCheck,
  active,
  onActivate,
}: FolderRowProps) {
  const { t } = useTranslation('knowledge')
  const indent = depth * (compact ? 12 : 16)

  const folderActions = canManageFolders ? (
    <span
      className="flex items-center gap-1 ml-auto flex-shrink-0"
      onClick={e => e.stopPropagation()}
    >
      {onCreateFolder && (
        <button
          className="p-1.5 rounded-md text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
          title={t('document.folder.create')}
          onClick={() => onCreateFolder(node.id)}
          data-testid={`create-subfolder-${node.id}`}
        >
          <FolderPlus className="w-3.5 h-3.5" />
        </button>
      )}
      {onRenameFolder && (
        <button
          className="p-1.5 rounded-md text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
          title={t('document.folder.rename')}
          onClick={() => onRenameFolder(node.id, node.name)}
          data-testid={`rename-folder-${node.id}`}
        >
          <Pencil className="w-3.5 h-3.5" />
        </button>
      )}
      {onDeleteFolder && (
        <button
          className="p-1.5 rounded-md text-text-muted hover:text-error hover:bg-error/10 transition-colors"
          title={t('document.folder.delete')}
          onClick={() => onDeleteFolder(node.id, node.name)}
          data-testid={`delete-folder-${node.id}`}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}
    </span>
  ) : null

  // Folder checkbox represents a backend-resolved folder scope, not current-page docs.
  const folderCheckbox = canSelectFolders ? (
    <Checkbox
      checked={folderChecked}
      disabled={folderSelectionDisabled || node.documentCount === 0}
      onCheckedChange={checked => {
        onFolderCheck?.(checked === true)
      }}
      onClick={e => e.stopPropagation()}
      className="data-[state=checked]:bg-primary data-[state=checked]:border-primary flex-shrink-0 disabled:opacity-60"
      data-testid={`folder-checkbox-${node.id}`}
    />
  ) : null

  if (compact) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-pressed={active}
        className={`flex items-center gap-2 w-full px-2 py-2 rounded-lg transition-colors text-left cursor-pointer ${
          active ? 'bg-primary/10 text-primary' : 'hover:bg-surface'
        }`}
        style={{ paddingLeft: `${8 + indent}px` }}
        onClick={() => onActivate?.(node.id)}
        onKeyDown={e => {
          if (e.currentTarget !== e.target) {
            return
          }
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onActivate?.(node.id)
          }
        }}
        title={node.name}
      >
        {folderCheckbox}
        {expanded ? (
          <ChevronDown
            className="w-3 h-3 text-text-muted flex-shrink-0"
            onClick={e => {
              e.stopPropagation()
              onToggle(node.path)
            }}
          />
        ) : (
          <ChevronRight
            className="w-3 h-3 text-text-muted flex-shrink-0"
            onClick={e => {
              e.stopPropagation()
              onToggle(node.path)
            }}
          />
        )}
        {expanded ? (
          <FolderOpen className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
        ) : (
          <Folder className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
        )}
        <span className="min-w-0 truncate text-xs font-medium text-text-primary">{node.name}</span>
        <span className="text-[10px] text-text-muted flex-shrink-0">
          {t('document.folder.docCount', { count: node.documentCount })}
        </span>
        {folderActions}
      </div>
    )
  }

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 transition-colors cursor-pointer border-b border-border min-w-[880px] ${
        active ? 'bg-primary/10 text-primary' : 'bg-surface/50 hover:bg-surface'
      }`}
      style={{ paddingLeft: `${16 + indent}px` }}
      onClick={() => onActivate?.(node.id)}
      role="button"
      tabIndex={0}
      aria-pressed={active}
      onKeyDown={e => {
        if (e.currentTarget !== e.target) {
          return
        }
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onActivate?.(node.id)
        }
      }}
    >
      {folderCheckbox}
      {expanded ? (
        <ChevronDown
          className="w-4 h-4 text-text-muted flex-shrink-0"
          onClick={e => {
            e.stopPropagation()
            onToggle(node.path)
          }}
        />
      ) : (
        <ChevronRight
          className="w-4 h-4 text-text-muted flex-shrink-0"
          onClick={e => {
            e.stopPropagation()
            onToggle(node.path)
          }}
        />
      )}
      {expanded ? (
        <FolderOpen className="w-4 h-4 text-amber-500 flex-shrink-0" />
      ) : (
        <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
      )}
      <span className="min-w-0 truncate text-sm font-medium text-text-primary">{node.name}</span>
      <span className="flex-shrink-0 text-xs text-text-muted">
        {t('document.folder.docCount', { count: node.documentCount })}
      </span>
      {folderActions}
    </div>
  )
}

function isCoveredBySelectedAncestorFolder(
  node: NodeApi<TreeNode>,
  selectedFolderIds?: Set<number>
): boolean {
  if (!selectedFolderIds || selectedFolderIds.size === 0) {
    return false
  }

  let parent = node.parent
  while (parent && !parent.isRoot) {
    if (parent.data.type === 'api-folder' && selectedFolderIds.has(parent.data.id)) {
      return true
    }
    parent = parent.parent
  }
  return false
}

function countVisibleNodes(nodes: TreeNode[], expandedFolders: Set<string>): number {
  let count = 0
  for (const node of nodes) {
    count += 1
    if (node.type === 'api-folder' && expandedFolders.has(node.path)) {
      count += countVisibleNodes(node.children, expandedFolders)
    }
  }
  return count
}

function getTreeRowHeight(compact: boolean) {
  return compact ? 48 : 49
}

function FolderTreeRow<T>({ attrs, innerRef, children }: RowRendererProps<T>) {
  const { onClick: _onClick, ...safeAttrs } = attrs
  return (
    <div {...safeAttrs} ref={innerRef}>
      {children}
    </div>
  )
}

/**
 * FolderTree renders stable folder navigation and current document results.
 */
export function FolderTree({
  folders = [],
  documents,
  compact = false,
  withBorder = true,
  onViewDetail,
  onEdit,
  onDelete,
  onRefresh,
  onReindex,
  onMove,
  refreshingDocId,
  reindexingDocId,
  canManage,
  canSelect,
  selectedIds,
  includedInFolderScope,
  onSelect,
  ragConfigured,
  nameColumnWidth,
  showActionsColumn,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  canManageFolders = false,
  canSelectFolders = false,
  selectedFolderIds,
  onSelectFolder,
  activeFolderId,
  onActivateFolder,
}: FolderTreeProps) {
  const tree = useMemo(() => buildMergedTree(folders, documents), [folders, documents])
  const treeRef = useRef<TreeApi<TreeNode> | undefined>(undefined)

  const defaultExpandedFolderPaths = useMemo(
    () => folders.map(folder => `folder:${folder.id}`),
    [folders]
  )
  const activeFolderPaths = useMemo(
    () => findFolderPathIds(folders, activeFolderId).map(id => `folder:${id}`),
    [folders, activeFolderId]
  )
  const resultDocumentFolderPaths = useMemo(() => {
    const paths = new Set<string>()
    for (const document of documents) {
      for (const id of findFolderPathIds(folders, document.folder_id)) {
        paths.add(`folder:${id}`)
      }
    }
    return Array.from(paths)
  }, [folders, documents])

  // Default: expand root-level folders only; active/result paths are expanded separately.
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    () => new Set(defaultExpandedFolderPaths)
  )

  const openFolderPaths = useCallback((paths: string[]) => {
    if (paths.length === 0) return
    setExpandedFolders(prev => {
      const next = new Set(prev)
      for (const path of paths) {
        next.add(path)
      }
      return next
    })
    for (const path of paths) {
      treeRef.current?.open(path)
    }
  }, [])

  useEffect(() => {
    openFolderPaths(defaultExpandedFolderPaths)
  }, [defaultExpandedFolderPaths, openFolderPaths])

  useEffect(() => {
    openFolderPaths(activeFolderPaths)
  }, [activeFolderPaths, openFolderPaths])

  useEffect(() => {
    openFolderPaths(resultDocumentFolderPaths)
  }, [resultDocumentFolderPaths, openFolderPaths])

  const handleToggleFolder = useCallback((path: string) => {
    setExpandedFolders(prev => {
      const next = new Set(prev)
      if (treeRef.current?.isOpen(path)) {
        next.add(path)
      } else {
        next.delete(path)
      }
      return next
    })
  }, [])

  const initialOpenState = useMemo(() => {
    const state: Record<string, boolean> = {}
    for (const path of defaultExpandedFolderPaths) {
      state[path] = true
    }
    return state
  }, [defaultExpandedFolderPaths])

  const treeHeight = useMemo(
    () => countVisibleNodes(tree, expandedFolders) * getTreeRowHeight(compact),
    [compact, expandedFolders, tree]
  )

  const renderNode = useCallback(
    ({ node }: NodeRendererProps<TreeNode>) => {
      const data = node.data
      const depth = node.level

      if (data.type === 'document') {
        const doc = data.document
        const docWithDisplayName = { ...doc, name: data.displayName }
        const includedByFolder = includedInFolderScope?.(doc) ?? false

        if (compact) {
          return (
            <div style={{ paddingLeft: `${depth * 12}px` }}>
              <DocumentItem
                document={docWithDisplayName}
                onViewDetail={onViewDetail ? () => onViewDetail(doc) : undefined}
                onEdit={onEdit ? () => onEdit(doc) : undefined}
                onDelete={onDelete ? () => onDelete(doc) : undefined}
                onRefresh={onRefresh ? () => onRefresh(doc) : undefined}
                onReindex={onReindex ? () => onReindex(doc) : undefined}
                onMove={onMove ? () => onMove(doc) : undefined}
                isRefreshing={refreshingDocId === doc.id}
                isReindexing={reindexingDocId === doc.id}
                canManage={canManage?.(doc) ?? true}
                canSelect={canSelect?.(doc) ?? false}
                showBorder={false}
                selected={selectedIds?.has(doc.id) ?? false}
                includedInFolderScope={includedByFolder}
                onSelect={onSelect}
                compact={true}
                ragConfigured={ragConfigured}
                showActionsColumn={showActionsColumn}
              />
            </div>
          )
        }

        return (
          <DocumentItem
            document={docWithDisplayName}
            indent={depth * 16}
            onViewDetail={onViewDetail ? () => onViewDetail(doc) : undefined}
            onEdit={onEdit ? () => onEdit(doc) : undefined}
            onDelete={onDelete ? () => onDelete(doc) : undefined}
            onRefresh={onRefresh ? () => onRefresh(doc) : undefined}
            onReindex={onReindex ? () => onReindex(doc) : undefined}
            onMove={onMove ? () => onMove(doc) : undefined}
            isRefreshing={refreshingDocId === doc.id}
            isReindexing={reindexingDocId === doc.id}
            canManage={canManage?.(doc) ?? true}
            canSelect={canSelect?.(doc) ?? false}
            showBorder={true}
            selected={selectedIds?.has(doc.id) ?? false}
            includedInFolderScope={includedByFolder}
            onSelect={onSelect}
            compact={false}
            ragConfigured={ragConfigured}
            nameColumnWidth={nameColumnWidth}
            showActionsColumn={showActionsColumn}
          />
        )
      }

      const directlySelectedFolder = selectedFolderIds?.has(data.id) ?? false
      const coveredBySelectedAncestorFolder = isCoveredBySelectedAncestorFolder(
        node,
        selectedFolderIds
      )
      const folderChecked = coveredBySelectedAncestorFolder || directlySelectedFolder
      const folderSelectionDisabled = coveredBySelectedAncestorFolder

      return (
        <FolderRow
          node={data}
          depth={depth}
          compact={compact}
          expanded={node.isOpen}
          onToggle={() => node.toggle()}
          onCreateFolder={onCreateFolder}
          onRenameFolder={onRenameFolder}
          onDeleteFolder={onDeleteFolder}
          canManageFolders={canManageFolders}
          canSelectFolders={canSelectFolders}
          folderChecked={folderChecked}
          folderSelectionDisabled={folderSelectionDisabled}
          onFolderCheck={checked => onSelectFolder?.(data.id, checked)}
          active={activeFolderId === data.id}
          onActivate={onActivateFolder}
        />
      )
    },
    [
      activeFolderId,
      canManage,
      canManageFolders,
      canSelect,
      canSelectFolders,
      compact,
      includedInFolderScope,
      nameColumnWidth,
      onActivateFolder,
      onCreateFolder,
      onDelete,
      onDeleteFolder,
      onEdit,
      onMove,
      onRefresh,
      onReindex,
      onRenameFolder,
      onSelect,
      onSelectFolder,
      onViewDetail,
      ragConfigured,
      refreshingDocId,
      reindexingDocId,
      selectedFolderIds,
      selectedIds,
      showActionsColumn,
    ]
  )

  const treeContent = (
    <Tree<TreeNode>
      ref={treeRef}
      data={tree}
      idAccessor={treeNodeKey}
      childrenAccessor={node => (node.type === 'api-folder' ? node.children : null)}
      openByDefault={false}
      initialOpenState={initialOpenState}
      onToggle={handleToggleFolder}
      disableDrag={true}
      disableDrop={true}
      disableEdit={true}
      disableMultiSelection={true}
      disableSelect={true}
      rowHeight={getTreeRowHeight(compact)}
      height={treeHeight}
      width="100%"
      indent={0}
      overscanCount={8}
      renderRow={FolderTreeRow}
      className={compact ? 'space-y-0.5' : undefined}
    >
      {renderNode}
    </Tree>
  )

  if (compact) {
    return <div className="space-y-0.5">{treeContent}</div>
  }

  if (withBorder) {
    return <div className="border border-border rounded-lg overflow-x-auto">{treeContent}</div>
  }

  return <>{treeContent}</>
}
