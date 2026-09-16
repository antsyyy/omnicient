import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { api } from '../api/client'
import EntityPanel from '../components/EntityPanel'
import InvestigationHeader from '../components/InvestigationHeader'
import type { WorkspaceView } from '../components/InvestigationHeader'
import InvestigationGraph from '../components/InvestigationGraph'
import LinkDialog from '../components/LinkDialog'
import ResultsList from '../components/ResultsList'
import RelationshipPanel from '../components/RelationshipPanel'
import IdentityProfilePanel from '../components/IdentityProfilePanel'
import LeadsPanel from '../components/LeadsPanel'
import PathExplorer from '../components/PathExplorer'
import Sidebar from '../components/Sidebar'
import type {
  ConfidenceLevel,
  FilterState,
  InvestigationDetail,
  InvestigationGraph as GraphPayload,
  PathHighlight,
  RelationshipType,
} from '../types'
import { CONFIDENCE_ORDER, ENTITY_TYPES } from '../lib/display'

const DEFAULT_FILTERS: FilterState = {
  entityTypes: new Set(ENTITY_TYPES),
  confidenceLevels: new Set<ConfidenceLevel>([...CONFIDENCE_ORDER, 'INSUFFICIENT']),
  showUnassociated: true,
  showDifferentIdentity: true,
}

const RUNNING = ['CREATED', 'CRAWLING', 'ANALYZING']

/**
 * The investigation workspace: graph in the centre, investigation context on
 * the left, the inspector on the right.
 */
type InspectorTab = 'profile' | 'leads' | 'paths'

/** The stages an analyst watches during a crawl (section 31). */
const CRAWL_STAGES = [
  { id: 'CREATED', label: 'Identifier detected' },
  { id: 'CRAWLING', label: 'Sources queried' },
  { id: 'ANALYZING', label: 'Correlating entities' },
] as const

const STAGE_ORDER = ['CREATED', 'CRAWLING', 'ANALYZING', 'COMPLETED']

function stageReached(
  investigation: InvestigationDetail,
  stage: string,
): boolean {
  return STAGE_ORDER.indexOf(investigation.status) > STAGE_ORDER.indexOf(stage)
}

function stageActive(
  investigation: InvestigationDetail,
  stage: string,
): boolean {
  return investigation.status === stage
}

interface Props {
  /** Which reading of the investigation this route shows. */
  view: WorkspaceView
}

export default function Investigation({ view }: Props) {
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
  const [tab, setTab] = useState<InspectorTab>('profile')
  const [highlight, setHighlight] = useState<PathHighlight | null>(null)
  /*
   * On by default. The canvas is where an analyst reviews what the crawl
   * found, and it cannot be that while the engine's proposals are hidden -
   * a fresh investigation drew one edge out of sixty-one. They are drawn
   * dashed and faint, which says "proposed" without asserting it.
   */
  const [showCandidates, setShowCandidates] = useState(true)
  // A pending link: two entity ids the analyst dragged together.
  const [pendingLink, setPendingLink] = useState<[string, string] | null>(null)
  const [linkError, setLinkError] = useState<string | null>(null)
  // Bumped whenever the graph changes, so the analysis panels refetch rather
  // than showing a profile computed from a stale graph.
  const [revision, setRevision] = useState(0)

  const load = useCallback(async () => {
    const detail = await api.getInvestigation(id)
    setInvestigation(detail)
    /*
     * The graph is read while the crawl is still running, not only after it
     * finishes. The backend writes each level out as it completes, so an
     * analyst watches accounts appear instead of a spinner - on two dozen
     * sources the first results are known long before the last one answers.
     */
    setGraph(await api.getGraph(id))
    // The analysis panels read the graph too; bumping this makes them
    // refetch, so a confirm or reject is reflected everywhere at once.
    setRevision((value) => value + 1)
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
    /*
     * Re-running discovery resets the investigation, which deletes every
     * entity - and with them any link the analyst drew by hand. That work has
     * no other copy, so it is never thrown away silently.
     */
    try {
      const existing = await api.getRelationships(id)
      const drawn = existing.filter((item) => item.origin === 'ANALYST').length
      if (
        drawn > 0 &&
        !window.confirm(
          `Re-running discovery rebuilds this investigation from scratch and ` +
            `will delete ${drawn} link${drawn === 1 ? '' : 's'} you drew by ` +
            `hand, along with the reasons recorded with them. Nothing the ` +
            `engine observed is lost — it is found again. Continue?`,
        )
      ) {
        return
      }
    } catch {
      // If the check itself fails, fall through rather than blocking the
      // crawl: the warning is a courtesy, not a gate.
    }

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

  const createLink = useCallback(
    async (type: RelationshipType, rationale: string) => {
      if (!pendingLink) return
      setBusy(true)
      setLinkError(null)
      try {
        await api.createLink(id, {
          source_entity_id: pendingLink[0],
          target_entity_id: pendingLink[1],
          relationship_type: type,
          rationale,
        })
        setPendingLink(null)
        await load()
      } catch (cause) {
        // Stays open with the reason: the analyst has typed a rationale and
        // should not lose it to a conflict they can correct.
        setLinkError((cause as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [id, load, pendingLink],
  )

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId)
    if (nodeId) setSelectedEdgeId(null)
  }, [])

  const selectEdge = useCallback((edgeId: string | null) => {
    setSelectedEdgeId(edgeId)
    if (edgeId) setSelectedNodeId(null)
  }, [])

  /** Analysis tabs live beside the graph; selection opens the detail tabs. */
  const analysisTabs: { id: InspectorTab; label: string }[] = [
    { id: 'profile', label: 'Profile' },
    { id: 'leads', label: 'Leads' },
    { id: 'paths', label: 'Paths' },
  ]

  const detail = useMemo(() => {
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
          // A ruling changes how the canvas draws the entity, and whether it
          // draws it at all, so the graph has to be re-read for it to show.
          onEntityChanged={load}
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
        view={view}
      />

      <div className="flex min-h-0 flex-1">
        <Sidebar
          investigation={investigation}
          graph={graph}
          filters={filters}
          onFiltersChange={setFilters}
          showFilters={view === 'graph'}
        />

        <main className="relative min-w-0 flex-1">
          {running && (
            <div className="absolute right-3 top-3 z-20">
              <div className="w-[300px] rounded-lg border border-accent/40 bg-panel/95 px-4 py-3 shadow-lg">
                <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
                  Analyzing investigation
                </div>
                <ul className="mt-3 space-y-1.5">
                  {CRAWL_STAGES.map((stage) => {
                    const done = stageReached(investigation, stage.id)
                    const active = stageActive(investigation, stage.id)
                    return (
                      <li
                        key={stage.id}
                        className="flex items-center gap-2 font-mono text-[11px]"
                        style={{
                          color: done
                            ? 'var(--color-confirmed)'
                            : active
                              ? 'var(--color-accent)'
                              : 'var(--color-faint)',
                        }}
                      >
                        <span className={active ? 'animate-pulse' : ''}>
                          {done ? '✓' : active ? '◉' : '○'}
                        </span>
                        {stage.label}
                      </li>
                    )
                  })}
                </ul>
                <div className="mt-3 border-t border-line pt-2 font-mono text-[11px] text-dim">
                  {investigation.entity_count}{' '}
                  {investigation.entity_count === 1 ? 'entity' : 'entities'} so far
                  <br />
                  {investigation.relationship_count} relationships analyzed
                </div>
                <div className="mt-1 text-[11px] leading-snug text-faint">
                  Results below update as each source answers.
                </div>
              </div>
            </div>
          )}

          {investigation.status === 'FAILED' && (
            <div className="absolute inset-x-0 top-0 z-10 border-b border-rejected/50 bg-rejected/10 px-4 py-2 text-[12px] text-rejected">
              Investigation failed: {investigation.status_message}
            </div>
          )}

          {/*
            Shown while the crawl is still running, which is the point: the
            backend writes each level out as it lands, so the rows fill in as
            sources answer instead of appearing all at once at the end.
          */}
          {view === 'list' ? (
            <ResultsList
              investigationId={investigation.id}
              revision={revision}
              selectedEntityId={selectedNodeId}
              onSelectEntity={selectNode}
              onSelectRelationship={selectEdge}
              onUpdated={() => void load()}
            />
          ) : graph && graph.nodes.length > 0 ? (
            <ReactFlowProvider>
              <InvestigationGraph
                graph={graph}
                filters={filters}
                showCandidates={showCandidates}
                onConnectRequest={(source, target) => {
                  setLinkError(null)
                  setPendingLink([source, target])
                }}
                selectedNodeId={selectedNodeId}
                selectedEdgeId={selectedEdgeId}
                focusNodeId={focusNodeId}
                layoutKey={layoutKey}
                highlight={highlight}
                onSelectNode={selectNode}
                onSelectEdge={selectEdge}
              />
            </ReactFlowProvider>
          ) : (
            !running && (
              <div className="flex h-full items-center justify-center px-8 text-center">
                <div className="max-w-md">
                  <div className="panel-title">No relationships discovered</div>
                  <p className="mt-2 text-[13px] leading-snug text-dim">
                    Omnicient could not find sufficient public evidence to
                    expand this investigation. The account may not exist, may be
                    private, or the platform may have declined the request — the
                    activity log has the exact reason for each source.
                  </p>
                  <p className="mt-2 text-[12px] leading-snug text-faint">
                    Try another identifier, or run discovery again.
                  </p>
                  <Link
                    to={`/investigations/${investigation.id}`}
                    className="mt-3 inline-block rounded border border-line px-2 py-1 font-mono text-[11px] text-dim hover:border-accent hover:text-accent"
                  >
                    See what each source answered
                  </Link>
                </div>
              </div>
            )
          )}

          {view === 'graph' && graph && graph.nodes.length > 0 && (
            <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
              <button
                onClick={() => setShowCandidates((value) => !value)}
                className="rounded border bg-panel/95 px-2 py-1 font-mono text-[11px]"
                style={{
                  borderColor: showCandidates
                    ? 'var(--color-accent)'
                    : 'var(--color-line)',
                  color: showCandidates
                    ? 'var(--color-accent)'
                    : 'var(--color-dim)',
                }}
                title="The engine's proposed links, which you have not ruled on yet"
              >
                {showCandidates ? 'hide candidates' : 'show candidates'}
              </button>
              <span className="rounded border border-line bg-panel/95 px-2 py-1 font-mono text-[11px] text-faint">
                drag one node onto another to link them
              </span>
            </div>
          )}

          {pendingLink && graph && (
            <LinkDialog
              source={graph.nodes.find((node) => node.id === pendingLink[0])!}
              target={graph.nodes.find((node) => node.id === pendingLink[1])!}
              busy={busy}
              error={linkError}
              onCancel={() => {
                setPendingLink(null)
                setLinkError(null)
              }}
              onSubmit={createLink}
            />
          )}

          {focusNodeId && view === 'graph' && (
            <button
              onClick={() => setFocusNodeId(null)}
              className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded border border-accent/60 bg-panel px-3 py-1 font-mono text-[11px] text-accent"
            >
              Focused on one entity · show the whole graph
            </button>
          )}
        </main>

        <section className="flex w-[380px] shrink-0 flex-col overflow-hidden border-l border-line bg-panel">
          <nav className="flex shrink-0 border-b border-line">
            {analysisTabs.map((entry) => (
              <button
                key={entry.id}
                onClick={() => {
                  setTab(entry.id)
                  selectNode(null)
                  selectEdge(null)
                }}
                className="flex-1 px-2 py-1.5 font-mono text-[11px] tracking-wide"
                style={{
                  color:
                    tab === entry.id && !detail
                      ? 'var(--color-accent)'
                      : 'var(--color-dim)',
                  borderBottom:
                    tab === entry.id && !detail
                      ? '2px solid var(--color-accent)'
                      : '2px solid transparent',
                }}
              >
                {entry.label}
              </button>
            ))}
            {detail && (
              <button
                onClick={() => {
                  selectNode(null)
                  selectEdge(null)
                }}
                className="px-2 py-1.5 font-mono text-[11px] text-accent"
                style={{ borderBottom: '2px solid var(--color-accent)' }}
                title="Back to the analysis panels"
              >
                Detail ✕
              </button>
            )}
          </nav>

          {detail ?? (
            <>
              {tab === 'profile' && (
                <IdentityProfilePanel
                  investigationId={investigation.id}
                  revision={revision}
                  onSelectEntity={selectNode}
                  onSelectRelationship={selectEdge}
                />
              )}
              {tab === 'leads' && (
                <LeadsPanel
                  investigationId={investigation.id}
                  revision={revision}
                  onSelectEntity={selectNode}
                  onSelectRelationship={selectEdge}
                  onHighlight={setHighlight}
                />
              )}
              {tab === 'paths' && (
                <PathExplorer
                  investigationId={investigation.id}
                  nodes={graph?.nodes ?? []}
                  selectedNodeId={selectedNodeId}
                  onSelectEntity={selectNode}
                  onSelectRelationship={selectEdge}
                  onHighlight={setHighlight}
                />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
