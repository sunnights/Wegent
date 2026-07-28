// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import { useEffect, useRef, useCallback } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { useSocket } from '@/contexts/SocketContext'
import type { Team } from '@/types/api'

/** Timeout (ms) for waiting WebSocket connection before giving up */
const WS_READY_TIMEOUT = 10_000

/** Polling interval (ms) for checking readiness conditions */
const POLL_INTERVAL = 200

interface QueryParamAutoSendProps {
  /** Available teams to select from */
  teams: Team[]
  /** Whether teams have finished loading */
  isTeamsLoading: boolean
  /** Currently selected team */
  selectedTeam: Team | null
  /** Callback to change the selected team */
  onTeamChange: (team: Team) => void
  /** Callback to send a message (same as manual send) */
  onSendMessage: (message: string) => Promise<void>
  /** Whether there is an existing task selected (taskId in URL) */
  hasTaskId: boolean
  /** Currently loaded task ID, used to avoid sending before an existing task is ready */
  currentTaskId?: number | null
  /** Callback to prefill the input box with the query text (called immediately on mount) */
  onPrefillMessage?: (message: string) => void
}

/**
 * Monitors URL query parameters `q`, `teamId`, `teamName`, `teamNamespace`, and `autoSend` to automatically
 * initiate or continue a conversation when the chat page is opened via an
 * external link like `/chat?q=hello&teamName=myAgent&teamNamespace=default&autoSend=true`.
 *
 * Behavior:
 * - Only fires when `q` is present and non-empty.
 * - `q` content is always prefilled into the input box immediately on mount.
 * - Auto-send only happens when `autoSend=true` is present in the URL.
 * - For a new task, waits for WebSocket connection + teams loaded before sending.
 * - For an existing task, waits until that exact task has loaded before sending.
 * - Clears `q`, `teamId`, `teamName`, `teamNamespace`, and `autoSend` from URL after sending (taskId is
 *   set by the normal send flow).
 * - Uses a ref guard to guarantee the message is sent at most once, even
 *   under React StrictMode double-render.
 */
export default function QueryParamAutoSend({
  teams,
  isTeamsLoading,
  selectedTeam,
  onTeamChange,
  onSendMessage,
  hasTaskId,
  currentTaskId,
  onPrefillMessage,
}: QueryParamAutoSendProps) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { isConnected } = useSocket()

  // Guard each external request while allowing later node questions in the same mounted chat.
  const processedRequestRef = useRef<string | null>(null)
  // Track if user manually interacted before auto-send fires
  const userInteractedRef = useRef(false)

  // Keep latest values in refs so setTimeout callbacks always read current state
  const isConnectedRef = useRef(isConnected)
  const isTeamsLoadingRef = useRef(isTeamsLoading)
  const teamsRef = useRef(teams)
  const selectedTeamRef = useRef(selectedTeam)
  const onTeamChangeRef = useRef(onTeamChange)
  const onSendMessageRef = useRef(onSendMessage)
  const currentTaskIdRef = useRef(currentTaskId)

  useEffect(() => {
    isConnectedRef.current = isConnected
  }, [isConnected])

  useEffect(() => {
    isTeamsLoadingRef.current = isTeamsLoading
  }, [isTeamsLoading])

  useEffect(() => {
    teamsRef.current = teams
  }, [teams])

  useEffect(() => {
    selectedTeamRef.current = selectedTeam
  }, [selectedTeam])

  useEffect(() => {
    onTeamChangeRef.current = onTeamChange
  }, [onTeamChange])

  useEffect(() => {
    onSendMessageRef.current = onSendMessage
  }, [onSendMessage])

  useEffect(() => {
    currentTaskIdRef.current = currentTaskId
  }, [currentTaskId])

  // Detect user interaction (typing / team switch) to cancel auto-send
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // Ignore modifier-only keys
      if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) return
      userInteractedRef.current = true
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Remove q, teamId, teamName, teamNamespace, and autoSend from URL without adding browser history entries
  const clearQueryParams = useCallback(() => {
    const url = new URL(window.location.href)
    url.searchParams.delete('q')
    url.searchParams.delete('teamId')
    url.searchParams.delete('teamName')
    url.searchParams.delete('teamNamespace')
    url.searchParams.delete('autoSend')
    url.searchParams.delete('autosend')
    url.searchParams.delete('requestId')
    router.replace(url.pathname + url.search)
  }, [router])

  // Prefill input box immediately when q param is present (even before auto-send conditions are met)
  const prefilledRequestRef = useRef<string | null>(null)
  useEffect(() => {
    const query = searchParams.get('q')
    if (!query) return
    const requestKey =
      searchParams.get('requestId') ??
      `${searchParams.get('taskId') ?? ''}:${query}:${searchParams.get('autoSend') ?? ''}`
    if (prefilledRequestRef.current === requestKey) return

    const decodedMessage = query.trim()
    if (!decodedMessage) return

    prefilledRequestRef.current = requestKey
    onPrefillMessage?.(decodedMessage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  useEffect(() => {
    const query = searchParams.get('q')
    if (!query) return
    const requestKey =
      searchParams.get('requestId') ??
      `${searchParams.get('taskId') ?? ''}:${query}:${searchParams.get('autoSend') ?? ''}`
    if (processedRequestRef.current === requestKey) return

    const decodedMessage = query.trim()
    if (!decodedMessage) return

    // Only auto-send when autoSend=true is explicitly set in the URL
    // Support both camelCase (autoSend) and lowercase (autosend) parameter names
    const autoSendParam = searchParams.get('autoSend') ?? searchParams.get('autosend')
    if (autoSendParam?.toLowerCase() !== 'true') {
      // No auto-send requested - just prefill (already done above) and stop
      processedRequestRef.current = requestKey
      return
    }

    const teamIdParam = searchParams.get('teamId')
    const targetTeamId = teamIdParam ? Number(teamIdParam) : null

    // Support team lookup by name and namespace (user-friendly alternative to teamId)
    const teamNameParam = searchParams.get('teamName')
    const teamNamespaceParam = searchParams.get('teamNamespace') || 'default'

    // Mark this request immediately to prevent duplicate triggers.
    processedRequestRef.current = requestKey
    userInteractedRef.current = false

    // Wait for prerequisites then send
    let cancelled = false
    const startTime = Date.now()

    const tryExecute = () => {
      if (cancelled) return
      if (userInteractedRef.current) {
        // User interacted, cancel auto-send but still clean URL params
        clearQueryParams()
        return
      }

      const elapsed = Date.now() - startTime

      // Read latest values from refs to avoid stale closure
      const connected = isConnectedRef.current
      const teamsLoading = isTeamsLoadingRef.current
      const currentTeams = teamsRef.current

      // Check WebSocket readiness
      if (!connected) {
        if (elapsed > WS_READY_TIMEOUT) {
          // Timeout - clean up params and give up
          clearQueryParams()
          return
        }
        // Retry after a short delay; polling is handled via setTimeout
        setTimeout(tryExecute, POLL_INTERVAL)
        return
      }

      if (hasTaskId) {
        const targetTaskId = Number(searchParams.get('taskId'))
        if (!Number.isInteger(targetTaskId) || currentTaskIdRef.current !== targetTaskId) {
          if (elapsed > WS_READY_TIMEOUT) {
            clearQueryParams()
            return
          }
          setTimeout(tryExecute, POLL_INTERVAL)
          return
        }
        executeAutoSend(decodedMessage)
        return
      }

      // Check teams loaded
      if (teamsLoading || currentTeams.length === 0) {
        if (elapsed > WS_READY_TIMEOUT) {
          clearQueryParams()
          return
        }
        setTimeout(tryExecute, POLL_INTERVAL)
        return
      }
      // Switch team if requested (by ID or by name+namespace)
      let targetTeam: Team | undefined

      if (targetTeamId) {
        // Lookup by ID (backward compatible)
        targetTeam = currentTeams.find(t => t.id === targetTeamId)
      } else if (teamNameParam) {
        // Lookup by name and namespace (user-friendly)
        targetTeam = currentTeams.find(
          t => t.name === teamNameParam && t.namespace === teamNamespaceParam
        )
      }

      if (targetTeam) {
        const currentSelectedTeam = selectedTeamRef.current
        if (currentSelectedTeam?.id !== targetTeam.id) {
          onTeamChangeRef.current(targetTeam)
          // Allow a tick for the team change to propagate
          setTimeout(() => {
            if (!cancelled && !userInteractedRef.current) {
              executeAutoSend(decodedMessage)
            }
          }, POLL_INTERVAL)
          return
        }
      }
      // Team not found or already selected - fall through to use current/default team

      executeAutoSend(decodedMessage)
    }

    const executeAutoSend = (message: string) => {
      if (cancelled || userInteractedRef.current) {
        clearQueryParams()
        return
      }
      // Clean URL params before sending; the send handler will set taskId
      clearQueryParams()
      onSendMessageRef.current(message).catch(() => {
        // Error handling is done inside onSendMessage (toast etc.)
      })
    }

    // Start the readiness polling
    tryExecute()

    return () => {
      cancelled = true
    }
    // We intentionally use a minimal dependency array.
    // The ref guards and the cancelled flag prevent double execution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, hasTaskId])

  return null
}
