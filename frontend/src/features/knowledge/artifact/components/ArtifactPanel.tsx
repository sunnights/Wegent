// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { ChevronRight, FileText, Network, Presentation, type LucideIcon } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/hooks/useTranslation'

export type KnowledgeWorkshopCapability = 'mind_map' | 'presentation' | 'briefing'

interface ArtifactPanelProps {
  availableDocumentCount: number
  onCreateDraft: (capability: KnowledgeWorkshopCapability) => void
}

interface CapabilityCardProps {
  icon: LucideIcon
  label: string
  description: string
  disabled: boolean
  onClick: () => void
  testId: string
}

function CapabilityCard({
  icon: Icon,
  label,
  description,
  disabled,
  onClick,
  testId,
}: CapabilityCardProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="group flex h-24 flex-col justify-between rounded-xl border border-border bg-surface p-3 text-left transition-all hover:-translate-y-0.5 hover:border-primary hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          onClick={onClick}
          disabled={disabled}
          data-testid={testId}
        >
          <div className="flex w-full items-center justify-between">
            <div className="rounded-lg bg-primary/10 p-2 text-primary transition-colors group-hover:bg-primary group-hover:text-white">
              <Icon className="h-5 w-5" />
            </div>
            <div className="rounded-full bg-base p-2 text-text-muted transition-colors group-hover:text-primary">
              <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </div>
          </div>
          <div className="mt-2 text-sm font-medium leading-5">{label}</div>
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        align="start"
        sideOffset={6}
        className="max-w-64 py-2 leading-5"
      >
        {description}
      </TooltipContent>
    </Tooltip>
  )
}

export function ArtifactPanel({ availableDocumentCount, onCreateDraft }: ArtifactPanelProps) {
  const { t } = useTranslation('knowledge')
  const disabled = availableDocumentCount === 0

  return (
    <div data-testid="artifact-panel">
      <TooltipProvider delayDuration={300}>
        <div className="grid grid-cols-2 gap-3">
          <CapabilityCard
            icon={Network}
            label={t('artifact.action.mind_map')}
            description={t('artifact.type.mindMapHint')}
            disabled={disabled}
            onClick={() => onCreateDraft('mind_map')}
            testId="artifact-type-mind-map"
          />
          <CapabilityCard
            icon={Presentation}
            label={t('artifact.action.presentation')}
            description={t('artifact.type.presentationHint')}
            disabled={disabled}
            onClick={() => onCreateDraft('presentation')}
            testId="artifact-type-presentation"
          />
          <CapabilityCard
            icon={FileText}
            label={t('artifact.action.briefing')}
            description={t('artifact.type.briefingHint')}
            disabled={disabled}
            onClick={() => onCreateDraft('briefing')}
            testId="artifact-type-briefing"
          />
        </div>
      </TooltipProvider>
      {disabled && (
        <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-text-secondary">
          {t('artifact.noDocumentsHint')}
        </p>
      )}
    </div>
  )
}
