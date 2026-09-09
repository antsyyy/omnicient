import { useEffect, useRef } from 'react'
import {
  Copy,
  Crosshair,
  ExternalLink,
  EyeOff,
  Network,
  PanelRight,
} from 'lucide-react'
import type { MindMapItem } from './layout/mindMapLayout'

interface Props {
  item: MindMapItem
  x: number
  y: number
  onOpen: () => void
  onFocus: () => void
  onExpand: () => void
  onHide: () => void
  onClose: () => void
}

/**
 * Right-click actions on an entity.
 *
 * Everything here acts on the investigation the analyst already has. Opening
 * a source URL is a deliberate navigation in a new tab; nothing fetches
 * external content on the analyst's behalf from a menu click.
 */
export default function ContextMenu({
  item,
  x,
  y,
  onOpen,
  onFocus,
  onExpand,
  onHide,
  onClose,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const dismiss = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('mousedown', dismiss)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('mousedown', dismiss)
      window.removeEventListener('keydown', escape)
    }
  }, [onClose])

  const actions = [
    { icon: PanelRight, label: 'Open entity', run: onOpen },
    { icon: Crosshair, label: 'Focus entity', run: onFocus },
    { icon: Network, label: 'Expand relationships', run: onExpand },
    {
      icon: Copy,
      label: 'Copy identifier',
      run: () => void navigator.clipboard?.writeText(item.label),
    },
    ...(item.node.url
      ? [
          {
            icon: ExternalLink,
            label: 'Open source URL',
            run: () =>
              window.open(item.node.url!, '_blank', 'noopener,noreferrer'),
          },
        ]
      : []),
    { icon: EyeOff, label: 'Hide entity', run: onHide },
  ]

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[176px] overflow-hidden rounded-lg border border-line py-1"
      style={{
        left: x,
        top: y,
        background: 'rgba(12,17,24,0.97)',
        backdropFilter: 'blur(10px)',
        boxShadow: '0 12px 34px rgba(0,0,0,0.6)',
      }}
    >
      <div className="truncate border-b border-line px-2.5 pb-1.5 pt-0.5 font-mono text-[10px] text-faint">
        {item.label}
      </div>
      {actions.map(({ icon: Icon, label, run }) => (
        <button
          key={label}
          onClick={() => {
            run()
            onClose()
          }}
          className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-dim transition-colors hover:bg-raised hover:text-ink"
        >
          <Icon size={12} className="shrink-0" />
          {label}
        </button>
      ))}
    </div>
  )
}
