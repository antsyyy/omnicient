import {
  Crosshair,
  Layers,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Search,
  Target,
} from 'lucide-react'

interface Props {
  onZoomIn: () => void
  onZoomOut: () => void
  onFitView: () => void
  onResetLayout: () => void
  onFocusSeed: () => void
  onToggleSearch: () => void
  onToggleCollapseAll: () => void
  onToggleFocus: () => void
  searchOpen: boolean
  allCollapsed: boolean
  focusActive: boolean
  canFocus: boolean
}

function Button({
  label,
  onClick,
  active,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  active?: boolean
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="flex h-7 w-7 items-center justify-center rounded transition-colors disabled:opacity-30"
      style={{
        color: active ? 'var(--color-accent)' : 'var(--color-dim)',
        background: active ? 'rgba(34,211,238,0.12)' : 'transparent',
      }}
    >
      {children}
    </button>
  )
}

const Divider = () => <div className="mx-0.5 h-4 w-px bg-line" />

/**
 * Floating canvas controls.
 *
 * Kept to navigation and framing — anything that changes the investigation
 * itself belongs in the header, not hovering over the board.
 */
export default function GraphToolbar({
  onZoomIn,
  onZoomOut,
  onFitView,
  onResetLayout,
  onFocusSeed,
  onToggleSearch,
  onToggleCollapseAll,
  onToggleFocus,
  searchOpen,
  allCollapsed,
  focusActive,
  canFocus,
}: Props) {
  return (
    <div
      className="absolute left-3 top-3 z-20 flex items-center gap-0.5 rounded-lg border border-line px-1 py-1"
      style={{
        background: 'rgba(12,17,24,0.92)',
        backdropFilter: 'blur(8px)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
      }}
    >
      <Button label="Zoom in" onClick={onZoomIn}>
        <Plus size={13} />
      </Button>
      <Button label="Zoom out" onClick={onZoomOut}>
        <Minus size={13} />
      </Button>
      <Button label="Fit investigation" onClick={onFitView}>
        <Maximize2 size={13} />
      </Button>
      <Divider />
      <Button label="Centre on seed" onClick={onFocusSeed}>
        <Target size={13} />
      </Button>
      <Button
        label={focusActive ? 'Clear focus' : 'Focus selected entity'}
        onClick={onToggleFocus}
        active={focusActive}
        disabled={!canFocus && !focusActive}
      >
        <Crosshair size={13} />
      </Button>
      <Divider />
      <Button
        label={allCollapsed ? 'Expand all categories' : 'Collapse all categories'}
        onClick={onToggleCollapseAll}
        active={allCollapsed}
      >
        <Layers size={13} />
      </Button>
      <Button label="Search the investigation" onClick={onToggleSearch} active={searchOpen}>
        <Search size={13} />
      </Button>
      <Divider />
      <Button label="Reset layout" onClick={onResetLayout}>
        <RotateCcw size={13} />
      </Button>
    </div>
  )
}
