// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  FolderPlus,
  Pencil,
  Trash2,
} from 'lucide-react'
import { hotkeysCoreFeature, syncDataLoaderFeature, type ItemInstance } from '@headless-tree/core'
import { useTree } from '@headless-tree/react'
import { Checkbox } from '@/components/ui/checkbox'
import { useTranslation } from '@/hooks/useTranslation'
import type { KnowledgeDocument, KnowledgeFolder } from '@/types/knowledge'
import { DocumentItem, getDocumentTableGridTemplate } from './DocumentItem'

type KnowledgeTreeItem =
  | {
      type: 'root'
      id: string
      name: string
      children: string[]
    }
  | {
      type: 'folder'
      id: string
      folderId: number
      name: string
      documentCount: number
      children: string[]
    }
  | {
      type: 'document'
      id: string
      name: string
      document: KnowledgeDocument
      children: string[]
    }

interface TreeData {
  items: Map<string, KnowledgeTreeItem>
  rootChildren: string[]
}

export interface KnowledgeDocumentTreeGridProps {
  folders: KnowledgeFolder[]
  documents: KnowledgeDocument[]
  canManageAllDocuments: boolean
  canManageAnyDocuments: boolean
  canUpload: boolean
  canManage: (doc: KnowledgeDocument) => boolean
  canSelect: (doc: KnowledgeDocument) => boolean
  selectedIds: Set<number>
  includedInFolderScope?: (doc: KnowledgeDocument) => boolean
  onSelect?: (doc: KnowledgeDocument, selected: boolean) => void
  onSelectAll: (checked: boolean) => void
  isAllSelected: boolean
  isPartialSelected: boolean
  paginationEnabled: boolean
  selectedFolderIds: Set<number>
  onSelectFolder: (folderId: number, selected: boolean) => void
  activeFolderId?: number
  onActivateFolder?: (folderId: number) => void
  onCreateFolder?: (parentId: number) => void
  onRenameFolder?: (folderId: number, currentName: string) => void
  onDeleteFolder?: (folderId: number, folderName: string) => void
  onViewDetail?: (doc: KnowledgeDocument) => void
  onEdit?: (doc: KnowledgeDocument) => void
  onDelete?: (doc: KnowledgeDocument) => void
  onRefresh?: (doc: KnowledgeDocument) => void
  onReindex?: (doc: KnowledgeDocument) => void
  onMove?: (doc: KnowledgeDocument) => void
  refreshingDocId?: number | null
  reindexingDocId?: number | null
  ragConfigured?: boolean
  nameColumnWidth?: number
  nameColumnRef?: React.RefObject<HTMLDivElement | null>
  onNameResizeMouseDown?: (event: React.MouseEvent<HTMLDivElement>) => void
  sortIcon: (field: 'name' | 'size' | 'createdAt' | 'updatedAt') => React.ReactNode
  onSort: (field: 'name' | 'size' | 'createdAt' | 'updatedAt') => void
}

const ROOT_ID = '__knowledge-root__'

function documentId(document: KnowledgeDocument) {
  return `doc:${document.id}`
}

function folderId(folderIdValue: number) {
  return `folder:${folderIdValue}`
}

function toDocumentItem(document: KnowledgeDocument): KnowledgeTreeItem {
  return {
    type: 'document',
    id: documentId(document),
    name: document.name,
    document,
    children: [],
  }
}

function buildFolderItem(
  folder: KnowledgeFolder,
  documentsByFolderId: Map<number, KnowledgeDocument[]>,
  items: Map<string, KnowledgeTreeItem>
): KnowledgeTreeItem {
  const childIds: string[] = []

  for (const child of folder.children) {
    const childItem = buildFolderItem(child, documentsByFolderId, items)
    childIds.push(childItem.id)
  }

  for (const document of documentsByFolderId.get(folder.id) ?? []) {
    const documentItem = toDocumentItem(document)
    items.set(documentItem.id, documentItem)
    childIds.push(documentItem.id)
  }

  const item: KnowledgeTreeItem = {
    type: 'folder',
    id: folderId(folder.id),
    folderId: folder.id,
    name: folder.name,
    documentCount: folder.total_document_count ?? folder.document_count,
    children: childIds,
  }
  items.set(item.id, item)
  return item
}

function collectKnownFolderIds(folders: KnowledgeFolder[], ids = new Set<number>()) {
  for (const folder of folders) {
    ids.add(folder.id)
    collectKnownFolderIds(folder.children, ids)
  }
  return ids
}

function buildTreeData(folders: KnowledgeFolder[], documents: KnowledgeDocument[]): TreeData {
  const items = new Map<string, KnowledgeTreeItem>()
  const documentsByFolderId = new Map<number, KnowledgeDocument[]>()

  for (const document of documents) {
    const parentFolderId = document.folder_id ?? 0
    documentsByFolderId.set(parentFolderId, [
      ...(documentsByFolderId.get(parentFolderId) ?? []),
      document,
    ])
  }

  const knownFolderIds = collectKnownFolderIds(folders)
  const rootChildren: string[] = []

  for (const folder of folders) {
    const folderItem = buildFolderItem(folder, documentsByFolderId, items)
    rootChildren.push(folderItem.id)
  }

  for (const document of documentsByFolderId.get(0) ?? []) {
    const documentItem = toDocumentItem(document)
    items.set(documentItem.id, documentItem)
    rootChildren.push(documentItem.id)
  }

  for (const document of documents) {
    const parentFolderId = document.folder_id ?? 0
    if (parentFolderId > 0 && !knownFolderIds.has(parentFolderId)) {
      const documentItem = toDocumentItem(document)
      items.set(documentItem.id, documentItem)
      rootChildren.push(documentItem.id)
    }
  }

  items.set(ROOT_ID, {
    type: 'root',
    id: ROOT_ID,
    name: 'Knowledge documents',
    children: rootChildren,
  })

  return { items, rootChildren }
}

function findFolderPathIds(
  folders: KnowledgeFolder[],
  targetId: number | undefined,
  path: number[] = []
): number[] {
  if (targetId === undefined) return []

  for (const folder of folders) {
    const nextPath = [...path, folder.id]
    if (folder.id === targetId) return nextPath

    const childPath = findFolderPathIds(folder.children, targetId, nextPath)
    if (childPath.length > 0) return childPath
  }

  return []
}

function collectDefaultExpandedItems(folders: KnowledgeFolder[], documents: KnowledgeDocument[]) {
  const expanded = new Set<string>()

  for (const folder of folders) {
    expanded.add(folderId(folder.id))
  }

  for (const document of documents) {
    for (const id of findFolderPathIds(folders, document.folder_id)) {
      expanded.add(folderId(id))
    }
  }

  return Array.from(expanded)
}

function useMergedExpandedItems(
  folders: KnowledgeFolder[],
  documents: KnowledgeDocument[],
  activeFolderId?: number
) {
  const defaultExpandedItems = useMemo(
    () => collectDefaultExpandedItems(folders, documents),
    [folders, documents]
  )
  const activeExpandedItems = useMemo(
    () => findFolderPathIds(folders, activeFolderId).map(folderId),
    [folders, activeFolderId]
  )
  const [expandedItems, setExpandedItems] = useState<string[]>([])

  useEffect(() => {
    setExpandedItems(previous => Array.from(new Set([...previous, ...defaultExpandedItems])))
  }, [defaultExpandedItems])

  useEffect(() => {
    if (activeExpandedItems.length === 0) return
    setExpandedItems(previous => Array.from(new Set([...previous, ...activeExpandedItems])))
  }, [activeExpandedItems])

  return [expandedItems, setExpandedItems] as const
}

function FolderCell({
  item,
  treeItem,
  canSelectFolders,
  selectedFolderIds,
  onSelectFolder,
  canManageFolders,
  showActionsColumn,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
}: {
  item: ItemInstance<KnowledgeTreeItem>
  treeItem: Extract<KnowledgeTreeItem, { type: 'folder' }>
  canSelectFolders: boolean
  selectedFolderIds: Set<number>
  onSelectFolder: (folderId: number, selected: boolean) => void
  canManageFolders: boolean
  showActionsColumn: boolean
  onCreateFolder?: (parentId: number) => void
  onRenameFolder?: (folderId: number, currentName: string) => void
  onDeleteFolder?: (folderId: number, folderName: string) => void
}) {
  const { t } = useTranslation('knowledge')
  const level = item.getItemMeta()?.level ?? 0
  const coveredBySelectedAncestor = (() => {
    let parent = item.getParent()
    while (parent && parent.getId() !== ROOT_ID) {
      const parentData = parent.getItemData()
      if (parentData.type === 'folder' && selectedFolderIds.has(parentData.folderId)) {
        return true
      }
      parent = parent.getParent()
    }
    return false
  })()
  const directlySelected = selectedFolderIds.has(treeItem.folderId)
  const checked = coveredBySelectedAncestor || directlySelected

  return (
    <div className="contents">
      {canSelectFolders && (
        <div onClick={event => event.stopPropagation()}>
          <Checkbox
            checked={checked}
            disabled={coveredBySelectedAncestor || treeItem.documentCount === 0}
            onCheckedChange={value => onSelectFolder(treeItem.folderId, value === true)}
            className="data-[state=checked]:bg-primary data-[state=checked]:border-primary disabled:opacity-60"
            data-testid={`folder-checkbox-${treeItem.folderId}`}
          />
        </div>
      )}

      <div
        className="flex items-center gap-2 min-w-0 overflow-hidden"
        style={{ paddingLeft: `${level * 16}px` }}
      >
        <button
          type="button"
          className="h-6 w-6 flex items-center justify-center rounded-md text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          onClick={event => {
            event.stopPropagation()
            if (item.isExpanded()) {
              item.collapse()
            } else {
              item.expand()
            }
          }}
          aria-label={
            item.isExpanded()
              ? t('document.folder.collapse', '收起文件夹')
              : t('document.folder.expand', '展开文件夹')
          }
          data-testid={`toggle-folder-${treeItem.folderId}`}
        >
          {item.isExpanded() ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
        {item.isExpanded() ? (
          <FolderOpen className="h-4 w-4 flex-shrink-0 text-primary" />
        ) : (
          <Folder className="h-4 w-4 flex-shrink-0 text-primary" />
        )}
        <span className="truncate text-sm font-medium text-text-primary">{treeItem.name}</span>
        <span className="text-xs text-text-muted flex-shrink-0">
          {t('document.folder.docCount', { count: treeItem.documentCount })}
        </span>
      </div>

      <div className="flex items-center justify-end">
        {canManageFolders && (
          <div className="flex items-center justify-end gap-1">
            {onCreateFolder && (
              <button
                className="p-1 rounded-md text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                onClick={event => {
                  event.stopPropagation()
                  onCreateFolder(treeItem.folderId)
                }}
                title={t('document.folder.create')}
                data-testid={`create-subfolder-${treeItem.folderId}`}
              >
                <FolderPlus className="h-3.5 w-3.5" />
              </button>
            )}
            {onRenameFolder && (
              <button
                className="p-1 rounded-md text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                onClick={event => {
                  event.stopPropagation()
                  onRenameFolder(treeItem.folderId, treeItem.name)
                }}
                title={t('document.folder.rename')}
                data-testid={`rename-folder-${treeItem.folderId}`}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {onDeleteFolder && (
              <button
                className="p-1 rounded-md text-text-muted hover:text-error hover:bg-error/10 transition-colors"
                onClick={event => {
                  event.stopPropagation()
                  onDeleteFolder(treeItem.folderId, treeItem.name)
                }}
                title={t('document.folder.delete')}
                data-testid={`delete-folder-${treeItem.folderId}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      <div className="text-center text-xs text-text-muted">-</div>
      <div className="text-center text-xs text-text-muted">-</div>
      <div className="text-center text-xs text-text-muted">-</div>
      <div className="text-center text-xs text-text-muted">-</div>
      <div className="text-center text-xs text-text-muted">-</div>
      <div className="text-center text-xs text-text-muted">-</div>
      {showActionsColumn && <div />}
    </div>
  )
}

export function KnowledgeDocumentTreeGrid({
  folders,
  documents,
  canManageAllDocuments,
  canManageAnyDocuments,
  canUpload,
  canManage,
  canSelect,
  selectedIds,
  includedInFolderScope,
  onSelect,
  onSelectAll,
  isAllSelected,
  isPartialSelected,
  paginationEnabled,
  selectedFolderIds,
  onSelectFolder,
  activeFolderId,
  onActivateFolder,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onViewDetail,
  onEdit,
  onDelete,
  onRefresh,
  onReindex,
  onMove,
  refreshingDocId,
  reindexingDocId,
  ragConfigured = true,
  nameColumnWidth,
  nameColumnRef,
  onNameResizeMouseDown,
  sortIcon,
  onSort,
}: KnowledgeDocumentTreeGridProps) {
  const { t } = useTranslation('knowledge')
  const treeData = useMemo(() => buildTreeData(folders, documents), [folders, documents])
  const [expandedItems, setExpandedItems] = useMergedExpandedItems(
    folders,
    documents,
    activeFolderId
  )

  const tree = useTree<KnowledgeTreeItem>({
    rootItemId: ROOT_ID,
    getItemName: item => item.getItemData().name,
    isItemFolder: item =>
      item.getItemData().type === 'folder' || item.getItemData().type === 'root',
    initialState: {
      expandedItems,
    },
    state: {
      expandedItems,
    },
    setExpandedItems,
    dataLoader: {
      getItem: itemId => treeData.items.get(itemId) ?? treeData.items.get(ROOT_ID)!,
      getChildren: itemId => treeData.items.get(itemId)?.children ?? [],
    },
    indent: 16,
    features: [syncDataLoaderFeature, hotkeysCoreFeature],
  })

  const showSelectionColumn = canManageAllDocuments
  const tableGridTemplate = getDocumentTableGridTemplate({
    showSelectionColumn,
    showActionsColumn: canManageAnyDocuments,
    nameColumnWidth,
  })

  return (
    <div className="border border-border rounded-lg overflow-x-auto">
      <div className="bg-base min-w-[880px] w-fit">
        <div
          className="grid items-center gap-4 px-4 py-2.5 bg-surface text-xs text-text-muted font-medium border-b border-border"
          style={{ gridTemplateColumns: tableGridTemplate }}
        >
          {canManageAllDocuments && (
            <div>
              <Checkbox
                checked={isPartialSelected ? 'indeterminate' : isAllSelected}
                onCheckedChange={onSelectAll}
                aria-label={
                  paginationEnabled
                    ? t('document.document.batch.selectCurrentPage')
                    : t('document.document.batch.selectAll')
                }
                className="data-[state=checked]:bg-primary data-[state=checked]:border-primary"
              />
            </div>
          )}
          <div ref={nameColumnRef} className="relative flex items-center gap-2 min-w-0">
            <div className="w-4 h-4 flex-shrink-0" />
            <button
              type="button"
              className="cursor-pointer hover:text-text-primary select-none"
              onClick={() => onSort('name')}
            >
              {t('document.document.columns.name')}
              {sortIcon('name')}
            </button>
            {onNameResizeMouseDown && (
              <div
                className="absolute top-0 right-0 bottom-0 w-3 cursor-col-resize z-10 group/resize flex items-center justify-center"
                onMouseDown={onNameResizeMouseDown}
                onClick={event => event.stopPropagation()}
              >
                <div className="w-0.5 h-3/4 rounded-full bg-border group-hover/resize:bg-primary/50 transition-colors" />
              </div>
            )}
          </div>
          <div />
          <div className="text-center">{t('document.document.columns.type')}</div>
          <button
            type="button"
            className="text-center cursor-pointer hover:text-text-primary select-none"
            onClick={() => onSort('size')}
          >
            {t('document.document.columns.size')}
            {sortIcon('size')}
          </button>
          <div className="text-center">{t('document.document.columns.createdBy')}</div>
          <button
            type="button"
            className="text-center cursor-pointer hover:text-text-primary select-none"
            onClick={() => onSort('createdAt')}
          >
            {t('document.document.columns.date')}
            {sortIcon('createdAt')}
          </button>
          <button
            type="button"
            className="text-center cursor-pointer hover:text-text-primary select-none"
            onClick={() => onSort('updatedAt')}
          >
            {t('document.document.columns.updatedAt')}
            {sortIcon('updatedAt')}
          </button>
          <div className="text-center">{t('document.document.columns.indexStatus')}</div>
          {canManageAnyDocuments && (
            <div className="text-center">{t('document.document.columns.actions')}</div>
          )}
        </div>

        <div {...tree.getContainerProps(t('document.document.columns.name'))}>
          {tree.getItems().map(item => {
            const treeItem = item.getItemData()

            if (treeItem.type === 'document') {
              return (
                <DocumentItem
                  key={treeItem.id}
                  document={treeItem.document}
                  onViewDetail={onViewDetail}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onRefresh={onRefresh}
                  onReindex={onReindex}
                  onMove={onMove}
                  isRefreshing={refreshingDocId === treeItem.document.id}
                  isReindexing={reindexingDocId === treeItem.document.id}
                  canManage={canManage(treeItem.document)}
                  canSelect={canSelect(treeItem.document)}
                  selected={selectedIds.has(treeItem.document.id)}
                  includedInFolderScope={includedInFolderScope?.(treeItem.document) ?? false}
                  onSelect={onSelect}
                  ragConfigured={ragConfigured}
                  nameColumnWidth={nameColumnWidth}
                  showActionsColumn={canManageAnyDocuments}
                  indent={(item.getItemMeta()?.level ?? 0) * 16}
                />
              )
            }

            if (treeItem.type === 'folder') {
              const itemProps = item.getProps()
              return (
                <div
                  key={treeItem.id}
                  {...itemProps}
                  className={`grid items-center gap-4 px-4 py-3 bg-base hover:bg-surface transition-colors group min-w-[880px] border-b border-border cursor-pointer ${activeFolderId === treeItem.folderId ? 'bg-primary/5' : ''}`}
                  style={{ gridTemplateColumns: tableGridTemplate }}
                  onClick={event => {
                    itemProps.onClick?.(event)
                    onActivateFolder?.(treeItem.folderId)
                  }}
                  data-testid={`folder-row-${treeItem.folderId}`}
                >
                  <FolderCell
                    item={item}
                    treeItem={treeItem}
                    canSelectFolders={canManageAllDocuments}
                    selectedFolderIds={selectedFolderIds}
                    onSelectFolder={onSelectFolder}
                    canManageFolders={canUpload}
                    showActionsColumn={canManageAnyDocuments}
                    onCreateFolder={onCreateFolder}
                    onRenameFolder={onRenameFolder}
                    onDeleteFolder={onDeleteFolder}
                  />
                </div>
              )
            }

            return null
          })}
        </div>
      </div>
    </div>
  )
}
