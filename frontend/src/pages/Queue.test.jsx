import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { QueueItem } from './Queue.jsx'

const baseRow = {
  id: '1',
  plate_text: 'กข1234',
  province: 'กรุงเทพมหานคร',
  confidence: 0.92,
  original_url: '/original.jpg',
  crop_url: '/crop.jpg',
}

function setup(overrides = {}) {
  const props = {
    r: { ...baseRow, ...overrides },
    busy: false,
    onConfirm: vi.fn(),
    onCorrect: vi.fn(),
    onDelete: vi.fn(),
    onToast: vi.fn(),
  }
  const utils = render(<QueueItem {...props} />)
  return { ...utils, props }
}

describe('QueueItem shortcuts', () => {
  it('confirms on Enter when not typing', () => {
    const { props } = setup()
    const container = screen.getByText('ผล OCR').closest('div')
    fireEvent.keyDown(container, { key: 'Enter' })
    expect(props.onConfirm).toHaveBeenCalledTimes(1)
  })

  it('saves correction on Ctrl+Enter', () => {
    const { props } = setup()
    const container = screen.getByText('ผล OCR').closest('div')
    fireEvent.keyDown(container, { key: 'Enter', ctrlKey: true })
    expect(props.onCorrect).toHaveBeenCalledTimes(1)
  })
})

describe('QueueItem delete confirmation', () => {
  it('opens delete modal and confirms delete', () => {
    const { props } = setup()
    const container = screen.getByText('ผล OCR').closest('div')
    fireEvent.keyDown(container, { key: 'Delete' })

    expect(screen.getByText('ยืนยันการลบรายการ')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ยืนยันการลบ' }))
    expect(props.onDelete).toHaveBeenCalledTimes(1)
  })
})
