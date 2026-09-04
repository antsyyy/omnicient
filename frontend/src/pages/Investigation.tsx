import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { api } from '../api/client'
import EntityPanel from '../components/EntityPanel'
import InvestigationGraph from '../components/InvestigationGraph'
import InvestigationHeader from '../components/InvestigationHeader'
import RelationshipPanel from '../components/RelationshipPanel'
import Sidebar from '../components/Sidebar'
import type {
  ConfidenceLevel,
  FilterState,
  InvestigationDetail,
  InvestigationGraph as GraphPayload,
} from '../types'
import { CONFIDENCE_ORDER, ENTITY_TYPES, RELATIONSHIP_TYPES } from '../lib/display'

const DEFAULT_FILTERS: FilterState = {
  entityTypes: new Set(ENTITY_TYPES),
  relationshipTypes: new Set(RELATIONSHIP_TYPES),
  confidenceLevels: new Set<ConfidenceLevel>([...CONFIDENCE_ORDER, 'INSUFFICIENT']),
  hideRejected: false,
  minScore: 0,
}

const RUNNING = ['CREATED', 'CRAWLING', 'ANALYZING']

/**
 * The investigation workspace: graph in the centre, investigation context on
 * the left, the inspector on the right.
 */
export default function Investigation() {
  const { id = '' } = useParams()
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null)
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null)
  const [layoutKey, setLayoutKey] = useState(0)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const detail = await api.getInvestigation(id)
    setInvestigation(detail)
    if (!RUNNING.includes(detail.status)) {
      setGraph(await api.getGraph(id))
    }
    return detail
  }, [id])

  useEffect(() => {
    let active = true
    load().catch((cause: Error) => active && setError(cause.message))
    return () => {
      active = false
    }
  }, [load])

  // While discovery is running the client polls; the crawl itself happens in
  // the backend, so a reload or a second browser sees the same progress.
  useEffect(() => {
    if (!investigation || !RUNNING.includes(investigation.status)) return
    const timer = window.setInterval(() => {
      load().catch(() => undefined)
    }, 1200)
    return () => window.clearInterval(timer)
  }, [investigation, load])

  const recrawl = useCallback(async () => {
    setBusy(true)
    try {
      await api.crawl(id, { reset: true })
      await load()
      setSelectedEdgeId(null)
      setSelectedNodeId(null)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }, [id, load])

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId)
    if (nodeId) setSelectedEdgeId(null)
  }, [])

  const selectEdge = useCallback((edgeId: string | null) => {
    setSelectedEdgeId(edgeId)
    if (edgeId) setSelectedNodeId(null)
  }, [])

  const inspector = useMemo(() => {
    if (selectedEdgeId) {
      return (
        <RelationshipPanel
          relationshipId={selectedEdgeId}
          onClose={() => setSelectedEdgeId(null)}
          onUpdated={() => void load()}
          onSelectEntity={selectNode}
        />
      )
    }
    if (selectedNodeId) {
      return (
        <EntityPanel
          entityId={selectedNodeId}
          focused={focusNodeId === selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
          onToggleFocus={(entityId) =>
            setFocusNodeId((current) => (current === entityId ? null : entityId))
          }
          onSelectRelationship={selectEdge}
        />
      )
    }
    return null
  }, [selectedEdgeId, selectedNodeId, focusNodeId, load, selectNode, selectEdge])

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <div>
          <div className="font-mono text-[13px] text-rejected">{error}</div>
          <a href="/" className="mt-2 inline-block text-[12px] text-accent hover:underline">
            Back to investigations
          </a>
        </div>
      </div>
    )
  }

  if (!investigation) {
    return (
      <div className="flex h-full items-center justify-center text-[13px] text-faint">
        Loading investigation…
      </div>
    )
  }

  const running = RUNNING.includes(investigation.status)

  return (
    <div className="flex h-full flex-col">
      <InvestigationHeader
        investigation={investigation}
        onRecrawl={recrawl}
        onResetLayout={() => setLayoutKey((value) => value + 1)}
        busy={busy}
      />

      <div className="flex min-h-0 flex-1">
        <Sidebar
          investigation={investigation}
          graph={graph}
          filters={filters}
          onFiltersChange={setFilters}
        />

        <main className="relative min-w-0 flex-1">
          {running && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-void/80">
              <div className="rounded border border-line bg-panel px-6 py-5 text-center">
                <div className="font-mono text-[13px] text-accent">
                  <span className="mr-2 animate-pulse">●</span>
                  {investigation.status === 'ANALYZING' ? 'Correlating…' : 'Crawling…'}
                </div>
                <div className="mt-2 font-mono text-[11px] text-faint">
                  entities {investigation.entity_count} · relationships{' '}
                  {investigation.relationship_count} · evidence{' '}
                  {investigation.evidence_count}
                </div>
              </div>
            </div>
          )}

          {investigation.status === 'FAILED' && (
            <div className="absolute inset-x-0 top-0 z-10 border-b border-rejected/50 bg-rejected/10 px-4 py-2 text-[12px] text-rejected">
              Investigation failed: {investigation.status_message}
            </div>
          )}

          {graph && graph.nodes.length > 0 ? (
            <ReactFlowProvider>
              <InvestigationGraph
                graph={graph}
                filters={filters}
                selectedNodeId={selectedNodeId}
                selectedEdgeId={selectedEdgeId}
                focusNodeId={focusNodeId}
                layoutKey={layoutKey}
                onSelectNode={selectNode}
                onSelectEdge={selectEdge}
              />
            </ReactFlowProvider>
          ) : (
            !running && (
              <div className="flex h-full items-center justify-center px-8 text-center">
                <div className="max-w-md">
                  <div className="panel-title">No entities</div>
                  <p className="mt-2 text-[13px] leading-snug text-dim">
                    Nothing publicly observable was found for this seed. The
                    account may not exist, may be private, or the platform may
                    have declined the request — see the activity log for the
                    exact reason.
                  </p>
                </div>
              </div>
            )
          )}

          {focusNodeId && (
            <button
              onClick={() => setFocusNodeId(null)}
              className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded border border-accent/60 bg-panel px-3 py-1 font-mono text-[11px] text-accent"
            >
              Focused on one entity · show the whole graph
            </button>
          )}
        </main>

        {inspector && (
          <section className="w-[360px] shrink-0 overflow-hidden border-l border-line bg-panel">
            {inspector}
          </section>
        )}
      </div>
    </div>
  )
}
