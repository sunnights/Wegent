// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { render, waitFor } from '@testing-library/react'
import QueryParamAutoSend from '@/features/tasks/components/params/QueryParamAutoSend'

const mockReplace = jest.fn()
let mockSearchParams = new URLSearchParams()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
}))

jest.mock('@/contexts/SocketContext', () => ({
  useSocket: () => ({ isConnected: true }),
}))

describe('QueryParamAutoSend', () => {
  beforeEach(() => {
    mockReplace.mockReset()
    mockSearchParams = new URLSearchParams(
      'taskId=42&q=%E8%A7%A3%E9%87%8A%E8%8A%82%E7%82%B9&autoSend=true&requestId=first'
    )
    window.history.replaceState(
      {},
      '',
      '/?taskId=42&q=%E8%A7%A3%E9%87%8A%E8%8A%82%E7%82%B9&autoSend=true&requestId=first'
    )
  })

  it('continues the loaded task for each distinct query request', async () => {
    const onSendMessage = jest.fn().mockResolvedValue(undefined)
    const onPrefillMessage = jest.fn()

    const view = render(
      <QueryParamAutoSend
        teams={[]}
        isTeamsLoading={false}
        selectedTeam={null}
        onTeamChange={jest.fn()}
        onSendMessage={onSendMessage}
        hasTaskId
        currentTaskId={42}
        onPrefillMessage={onPrefillMessage}
      />
    )

    await waitFor(() => expect(onSendMessage).toHaveBeenCalledWith('解释节点'))
    expect(onPrefillMessage).toHaveBeenCalledWith('解释节点')
    expect(mockReplace).toHaveBeenCalledWith('/?taskId=42')

    mockSearchParams = new URLSearchParams(
      'taskId=42&q=%E8%A7%A3%E9%87%8A%E8%8A%82%E7%82%B9&autoSend=true&requestId=second'
    )
    window.history.replaceState(
      {},
      '',
      '/?taskId=42&q=%E8%A7%A3%E9%87%8A%E8%8A%82%E7%82%B9&autoSend=true&requestId=second'
    )
    view.rerender(
      <QueryParamAutoSend
        teams={[]}
        isTeamsLoading={false}
        selectedTeam={null}
        onTeamChange={jest.fn()}
        onSendMessage={onSendMessage}
        hasTaskId
        currentTaskId={42}
        onPrefillMessage={onPrefillMessage}
      />
    )

    await waitFor(() => expect(onSendMessage).toHaveBeenCalledTimes(2))
  })

  it('does not send before the target task has loaded', () => {
    const onSendMessage = jest.fn().mockResolvedValue(undefined)

    render(
      <QueryParamAutoSend
        teams={[]}
        isTeamsLoading={false}
        selectedTeam={null}
        onTeamChange={jest.fn()}
        onSendMessage={onSendMessage}
        hasTaskId
        currentTaskId={41}
      />
    )

    expect(onSendMessage).not.toHaveBeenCalled()
  })
})
