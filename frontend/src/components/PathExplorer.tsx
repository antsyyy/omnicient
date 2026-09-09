import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type {
  GraphNode,
  PathHighlight,
  PathResponse,
  RelationshipPath,
} from '../types'

interface Props {
  investigationId: string
  nodes: GraphNode[]
  /** Pre-selects the source, so "how does this connect?" starts from selection. */
  selectedNodeId: string | null
  onSelectEntity: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
  onHighlight: (highlight: PathHighlight | null) => void
}

const STRENGTH_COLOR: Record<string, string> = {
  STRONG: 'var(--color-confirmed)',
  MODERATE: 'var(--color-band-medium)',
  WEAK: 'var(--color-dim)',
  REJECTED: 'var(--color-rejected)',
}

function EntitySelect({
  label,
  value,
  nodes,
  exclude,
  onChange,
}: {
  label: string
  value: string
  nodes: GraphNode[]
  exclude: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="panel-title">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-0.5 w-full rounded border border-line bg-void px-2 py-1 font-mono text-[11px] text-ink outline-none focus:border-accent"
      >
        <option value="">Select an entity…</option>
        {nodes
          .filter((node) => node.id !== exclude)
          .map((node) => (
            <option key={node.id} value={node.id}>
              {node.platform_name} · {node.label}
            </option>
          ))}
      </select>
    </label>
  )
}

function PathCard({
  path,
  active,
  onActivate,
  onSelectEntity,
  onSelectRelationship,
}: {
  path: RelationshipPath
  active: boolean
  onActivate: () => void
  onSelectEntity: (id: string) => void
  onSelectRelationship: (id: string) => void
}) {
  const color = STRENGTH_COLOR[path.strength] ?? STRENGTH_COLOR.WEAK

  return (
    <li
      className="border-b border-line px-3 py-2 last:border-b-0"
      style={active ? { background: 'var(--color-raised)' } : undefined}
    >
      <button onClick={onActivate} className="flex w-full items-center gap-2 text-left">
        <span className="font-mono text-[10px] text-faint">#{path.rank}</span>
        <span className="font-mono text-[10px]" style={{ color }}>
          {path.strength}
        </span>
        <span className="font-mono text-[10px] text-faint">
          {path.length} hop{path.length === 1 ? '' : 's'}
        </span>
        {path.has_contradictions && (
          <span className="font-mono text-[10px] text-contradiction">
            {path.contradictions} contradiction
            {path.contradictions === 1 ? '' : 's'}
          </span>
        )}
        <span className="ml-auto font-mono text-[9px] text-faint">
          {active ? 'shown' : 'show'}
        </span>
      </button>

      <ol className="mt-1.5 border-l border-line pl-2">
        <li className="py-[2px]">
          <button
            onClick={() => onSelectEntity(path.start.id)}
            className="font-mono text-[11px] text-ink hover:text-accent"
          >
            {path.start.platform_name} {path.start.name}
          </button>
        </li>
        {path.steps.map((step, index) => (
          <li key={`${step.relationship_id}-${index}`} className="py-[2px]">
            <button
              onClick={() => onSelectRelationship(step.relationship_id)}
              className="block font-mono text-[9px] uppercase tracking-wide text-faint hover:text-accent"
              title={`${step.evidence_count} evidence item(s)`}
            >
              {step.reversed ? '↑' : '↓'} {step.relationship_label}
            </button>
            <button
              onClick={() => onSelectEntity(step.entity.id)}
              className="font-mono text-[11px] text-ink hover:text-accent"
            >
              {step.entity.platform_name} {step.entity.name}
            </button>
          </li>
        ))}
      </ol>
    </li>
  )
}

/**
 * Relationship path explorer: how are these two entities connected?
 *
 * Routes are ranked deterministically — a rejected step sinks a route, fewer
 * contradictions and fewer hops win — and selecting one highlights it in the
 * graph, which is where the answer is actually legible.
 */
export default function PathExplorer({
  investigationId,
  nodes,
  selectedNodeId,
  onSelectEntity,
  onSelectRelationship,
  onHighlight,
}: Props) {
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [result, setResult] = useState<PathResponse | null>(null)
  const [activeRank, setActiveRank] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Selecting a node in the graph seeds the question.
  useEffect(() => {
    if (selectedNodeId && !source) setSource(selectedNodeId)
  }, [selectedNodeId, source])

  const sorted = useMemo(
    () => [...nodes].sort((a, b) => a.label.localeCompare(b.label)),
    [nodes],
  )

  async function search() {
    if (!source || !target) return
    setBusy(true)
    setError(null)
    setActiveRank(null)
    onHighlight(null)
    try {
      setResult(await api.findPaths(investigationId, source, target))
    } catch (cause) {
      setError((cause as Error).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  function activate(path: RelationshipPath) {
    if (activeRank === path.rank) {
      setActiveRank(null)
      onHighlight(null)
      return
    }
    setActiveRank(path.rank)
    onHighlight({
      nodeIds: new Set(path.node_ids),
      edgeIds: new Set(path.relationship_ids),
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="space-y-2 border-b border-line px-3 py-2.5">
        <EntitySelect
          label="From"
          value={source}
          nodes={sorted}
          exclude={target}
          onChange={setSource}
        />
        <EntitySelect
          label="To"
          value={target}
          nodes={sorted}
          exclude={source}
          onChange={setTarget}
        />
        <button
          onClick={() => void search()}
          disabled={!source || !target || busy}
          className="w-full rounded border border-accent/60 bg-accent/15 px-2 py-1 text-[12px] text-accent hover:bg-accent/25 disabled:opacity-40"
        >
          {busy ? 'Searching…' : 'Find connection path'}
        </button>
        {error && <p className="text-[11px] text-rejected">{error}</p>}
      </div>

      {result && (
        <>
          <p className="border-b border-line px-3 py-1.5 text-[11px] text-dim">
            {result.message}
          </p>
          {result.paths.length > 0 && (
            <ul>
              {result.paths.map((path) => (
                <PathCard
                  key={`${path.rank}-${path.relationship_ids.join('-')}`}
                  path={path}
                  active={activeRank === path.rank}
                  onActivate={() => activate(path)}
                  onSelectEntity={onSelectEntity}
                  onSelectRelationship={onSelectRelationship}
                />
              ))}
            </ul>
          )}
        </>
      )}

      {!result && !error && (
        <p className="px-3 py-2.5 text-[11px] leading-snug text-faint">
          Choose two entities to see how the discovered evidence connects them.
          Routes are ranked by evidence strength, analyst decisions, length and
          contradictions.
        </p>
      )}
    </div>
  )
}
