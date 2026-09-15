import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import EntityNode, { type EntityNodeData } from './EntityNode'
import type {
  FilterState,
  InvestigationGraph as GraphPayload,
  PathHighlight,
  RelationshipType,
} from '../types'
import {
  ASSERTED_COLOR,
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  CONFIDENCE_ORDER,
} from '../lib/display'

/**
 * Relationships that were read off a page rather than inferred from one.
 *
 * "This profile links to that site" is an observation: the anchor tag is
 * there, and no reasoning stands between the page and the claim. Nothing
 * about it is waiting on an analyst's judgement, so it is drawn solid and
 * drawn always - the same treatment a confirmed inference gets, for the same
 * reason, which is that neither one is a guess.
 */
const OBSERVED = new Set<RelationshipType>(['LINKS_TO', 'REFERENCES'])

function isObserved(edge: GraphPayload['edges'][number]): boolean {
  return OBSERVED.has(edge.relationship_type)
}

/**
 * Whether an edge asserts something, as opposed to proposing it.
 *
 * Three ways to qualify: an analyst confirmed it, an analyst drew it, or
 * nobody inferred anything in the first place because it was observed.
 *
 * This used to require one of the first two, which meant a crawl's entire
 * output stayed off the canvas until somebody clicked through a list - on a
 * typical investigation, one edge drawn out of sixty-one - and it put
 * observed links behind the same gate, asking an analyst to confirm that a
 * page contains a link the crawler read from it.
 */
function isEstablished(edge: GraphPayload['edges'][number]): boolean {
  return (
    edge.analyst_status === 'CONFIRMED' || edge.origin === 'ANALYST' || isObserved(edge)
  )
}

const nodeTypes = { entity: EntityNode }

/*
 * Dash patterns, shared by the canvas and the legend.
 *
 * The legend used to draw its samples with CSS `border-dashed`, which meant
 * the two dashed meanings - proposed, and contradicted - came out looking
 * identical in the key while the canvas drew them differently. A legend that
 * does not match the drawing is worse than none, so both now read from here.
 */
/** Where the expanded/collapsed choice is remembered. */
const LEGEND_KEY = 'omnicient.graph.legend'

const DASH_PROPOSED = '2 5'
const DASH_CONTRADICTED = '5 4'

/** One sample of an edge, drawn exactly as the canvas draws it. */
function Stroke({
  color,
  dash,
  width = 1.5,
}: {
  color: string
  dash?: string
  width?: number
}) {
  return (
    <svg width="18" height="6" viewBox="0 0 18 6" className="shrink-0" aria-hidden="true">
      <line
        x1="0"
        y1="3"
        x2="18"
        y2="3"
        stroke={color}
        strokeWidth={width}
        strokeDasharray={dash}
      />
    </svg>
  )
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-1.5 font-mono text-[10px]">{children}</li>
  )
}

/**
 * What the drawing means.
 *
 * Two channels, and the key is split the way they are. Colour is the
 * confidence band. Stroke is standing - who puts their name to the line -
 * which is where contradicted, rejected and analyst-asserted belong too:
 * none of those is a band, and listing them under "Confidence" (as this
 * did) quietly undoes the one-channel-one-meaning rule the canvas follows.
 *
 * Collapsible, because it is a key and not a control: once an analyst has
 * learned it they want the canvas back. The counts stay visible either way,
 * since those change as filters move and are worth watching.
 */
function Legend({
  shown,
  total,
  edges,
  showCandidates,
  open,
  onToggle,
}: {
  shown: number
  total: number
  edges: number
  showCandidates: boolean
  open: boolean
  onToggle: () => void
}) {
  const counts = `${shown} of ${total} entities · ${edges} ${
    edges === 1 ? 'connection' : 'connections'
  }`

  return (
    <div
      // Fixed width open so the rows align; shrink-to-fit closed.
      className={`rounded-md border border-line bg-panel/95 ${
        open ? 'w-[228px]' : 'w-auto'
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        title={open ? 'Hide the key' : 'Show the key'}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-dim hover:bg-line/40 hover:text-ink"
      >
        {/*
          An SVG rather than a ▾ character: the interface's monospace stack
          has no geometric-shape glyphs, so the character fell back to a dot
          and the control read as a speck of dust.
        */}
        <svg
          width="8"
          height="8"
          viewBox="0 0 8 8"
          aria-hidden="true"
          className={`shrink-0 transition-transform ${open ? '' : '-rotate-90'}`}
        >
          <path d="M1 2.5 L4 6 L7 2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <span className="panel-title flex-1">Key</span>
        {!open && (
          <span className="font-mono text-[10px] text-faint">{edges}</span>
        )}
      </button>

      {open && (
        <div className="px-2.5 pb-2">
          <div className="panel-title mb-1.5">Confidence</div>
          <ul className="space-y-1">
            {CONFIDENCE_ORDER.map((level) => (
              <Key key={level}>
                <Stroke color={CONFIDENCE_COLOR[level]} width={2} />
                <span className="text-dim">{CONFIDENCE_LABEL[level]}</span>
              </Key>
            ))}
          </ul>

          <div className="panel-title mb-1.5 mt-2 border-t border-line pt-2">
            Standing
          </div>
          <ul className="space-y-1">
            <Key>
              <Stroke color="var(--color-dim)" width={2.5} />
              <span className="text-dim">Confirmed, or read off a page</span>
            </Key>
            {showCandidates && (
              <Key>
                <Stroke color="var(--color-faint)" dash={DASH_PROPOSED} width={1} />
                <span className="text-faint">Proposed, not yet ruled on</span>
              </Key>
            )}
            <Key>
              <Stroke
                color="var(--color-contradiction)"
                dash={DASH_CONTRADICTED}
                width={1.5}
              />
              <span className="text-dim">Contradicted, or rejected</span>
            </Key>
            <Key>
              <Stroke color={ASSERTED_COLOR} width={2.5} />
              <span className="text-dim">Asserted by you</span>
            </Key>
          </ul>

          <div className="mt-1.5 border-t border-line pt-1.5 font-mono text-[10px] text-faint">
            A dashed node border means referenced, never read.
          </div>
          <div className="mt-1 font-mono text-[10px] text-faint">{counts}</div>
        </div>
      )}
    </div>
  )
}

interface Props {
  graph: GraphPayload
  filters: FilterState
  /**
   * Draw the engine's unreviewed proposals too, dashed and faint.
   *
   * On by default, because a review surface that hides what there is to
   * review is not one. Turning it off leaves only what a person stands
   * behind - confirmed, asserted, or read straight off a page - which is the
   * right picture to export or present from.
   */
  showCandidates: boolean
  /** Ask to draw a link between two entities. */
  onConnectRequest: (sourceId: string, targetId: string) => void
  selectedNodeId: string | null
  selectedEdgeId: string | null
  focusNodeId: string | null
  /**
   * Nodes and edges to spotlight — a selected path, or the entities behind a
   * lead. Everything outside it dims rather than disappearing, so the route
   * stays legible in the context of the whole graph.
   */
  highlight: PathHighlight | null
  layoutKey: number
  onSelectNode: (id: string | null) => void
  onSelectEdge: (id: string | null) => void
}

/**
 * The investigation graph.
 *
 * Layout comes from the backend (depth-layered, deterministic); this component
 * owns interaction: selection, dragging, zoom, filtering and focus. Analyst
 * drags are remembered until the layout is reset.
 */
export default function InvestigationGraph({
  graph,
  filters,
  showCandidates,
  onConnectRequest,
  selectedNodeId,
  selectedEdgeId,
  focusNodeId,
  highlight,
  layoutKey,
  onSelectNode,
  onSelectEdge,
}: Props) {
  const { fitView } = useReactFlow()
  const dragged = useRef<Record<string, { x: number; y: number }>>({})

  /*
   * Whether the key is expanded, remembered across visits.
   *
   * A per-viewer convenience and nothing more, so localStorage is the right
   * home for it - but it throws outright in a private window or with site
   * data blocked, and an exception here would take the whole canvas down
   * with it. Hence the guards, and an expanded default when it cannot be
   * read: showing the key to someone who already knows it costs a corner of
   * the canvas, hiding it from someone who does not costs them the meaning.
   */
  const [legendOpen, setLegendOpen] = useState(() => {
    try {
      return window.localStorage.getItem(LEGEND_KEY) !== 'closed'
    } catch {
      return true
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(LEGEND_KEY, legendOpen ? 'open' : 'closed')
    } catch {
      // A browser that refuses storage still gets a working toggle, just not
      // a remembered one.
    }
  }, [legendOpen])


  /**
   * Edges that survive the current filter set.
   *
   * Only two questions now: has this been established, and was it rejected.
   * Which entities are on screen is decided below, and an edge between two
   * visible entities is always drawn - a line whose endpoints are both
   * present but which is hidden by a filter of its own is just confusing.
   */
  const visibleEdges = useMemo(
    () =>
      graph.edges.filter((edge) => {
        if (!isEstablished(edge) && !showCandidates) return false
        // A rejected edge is a decision, not a candidate: never redrawn.
        return edge.analyst_status !== 'REJECTED'
      }),
    [graph.edges, showCandidates],
  )

  /**
   * Nodes that survive the filters.
   *
   * Confidence is applied here rather than to the edges, and that is the
   * whole of the fix. Every entity found stays on the canvas whether or not
   * anything connects it yet - but which entities those are is exactly what
   * an analyst wants to narrow, and a band applied to edges narrowed nothing
   * they could see: the canvas only draws associations somebody has
   * confirmed, so the filter was being applied to lines that were already
   * hidden. Unchecking "Low · 127" changed nothing at all.
   *
   * A node's band is the strongest association touching it. An entity
   * nothing has associated yet has no band, and is kept or hidden by its own
   * control rather than vanishing when the first band is unchecked.
   */
  const visibleNodeIds = useMemo(
    () =>
      new Set(
        graph.nodes
          .filter((node) => filters.entityTypes.has(node.type))
          /*
           * Organizations are not drawn here at all. An employer or a school
           * is an attribute of a profile rather than an identity in its own
           * right, and one Facebook Intro puts eight of them on the canvas -
           * two thirds of the graph, as peers of the accounts they swamp.
           * They are still collected, still scored as shared-organization
           * evidence, and still listed on the profile panel; they are simply
           * not nodes.
           */
          .filter((node) => node.type !== 'ORGANIZATION')
          .filter((node) =>
            node.confidence_level === null
              ? filters.showUnassociated
              : filters.confidenceLevels.has(node.confidence_level),
          )
          .map((node) => node.id),
      ),
    [
      graph.nodes,
      filters.entityTypes,
      filters.confidenceLevels,
      filters.showUnassociated,
    ],
  )

  /** In focus mode, everything but the focused node and its neighbours dims. */
  const focusNeighbours = useMemo(() => {
    if (!focusNodeId) return null
    const neighbours = new Set<string>([focusNodeId])
    visibleEdges.forEach((edge) => {
      if (edge.source === focusNodeId) neighbours.add(edge.target)
      if (edge.target === focusNodeId) neighbours.add(edge.source)
    })
    return neighbours
  }, [focusNodeId, visibleEdges])

  const derivedNodes = useMemo<Node[]>(
    () =>
      graph.nodes
        .filter((node) => visibleNodeIds.has(node.id))
        .map((node) => ({
          id: node.id,
          type: 'entity',
          position: dragged.current[node.id] ?? node.position,
          selected: node.id === selectedNodeId,
          data: {
            node,
            dimmed:
              (focusNeighbours ? !focusNeighbours.has(node.id) : false) ||
              (highlight ? !highlight.nodeIds.has(node.id) : false),
            highlighted: highlight ? highlight.nodeIds.has(node.id) : false,
          } satisfies EntityNodeData,
        })),
    [graph.nodes, visibleNodeIds, selectedNodeId, focusNeighbours, highlight],
  )


  /*
   * Edge labels are the first thing to overwhelm this diagram. On a small
   * graph every label is readable and worth showing; past that they overlap
   * into noise, so only the edges an analyst has singled out keep theirs.
   */
  const labelEveryEdge = visibleEdges.length <= 24

  const derivedEdges = useMemo<Edge[]>(
    () =>
      visibleEdges
        .filter(
          (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
        )
        .map((edge) => {
          const contradictory =
            edge.relationship_type === 'CONTRADICTORY' || edge.contradiction_count > 0
          const rejected = edge.analyst_status === 'REJECTED'
          const asserted = edge.origin === 'ANALYST'
          const confirmed = edge.analyst_status === 'CONFIRMED'
          // An inference nobody has ruled on yet. Drawn, because hiding the
          // engine's output makes it unreviewable - but drawn dashed, so it
          // cannot be mistaken for something a person stands behind.
          const candidate = !isEstablished(edge)
          const onPath = highlight ? highlight.edgeIds.has(edge.id) : false
          const dimmed =
            (focusNeighbours
              ? !(focusNeighbours.has(edge.source) && focusNeighbours.has(edge.target))
              : false) ||
            (highlight ? !onPath : false)
          const color = rejected
            ? 'var(--color-rejected)'
            : asserted
              ? ASSERTED_COLOR
              : contradictory
                ? 'var(--color-contradiction)'
                : CONFIDENCE_COLOR[edge.confidence_level]
          const labelled =
            labelEveryEdge || onPath || edge.id === selectedEdgeId
          return {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            /*
             * Straight, because the layout is radial: entities sit on rings
             * around the seed, so a line between two of them is a spoke or a
             * chord and reads as one. Orthogonal routing fought that - with
             * only confirmed edges drawn it was rarely visible, but once the
             * engine's proposals are on the canvas the right-angle detours
             * overlap into large rectangles that look like structure and are
             * only routing.
             */
            type: 'straight',
            selected: edge.id === selectedEdgeId,
            animated: edge.relationship_type === 'POTENTIAL_SAME_IDENTITY',
            /*
             * An asserted link has no score to show. Printing a 0 next to it
             * would read as "the evidence is weak" when the truth is that
             * there is no engine evidence at all - a person vouched for it.
             */
            label: labelled
              ? asserted
                ? `${edge.relationship_label} · asserted`
                : `${edge.relationship_label} · ${Math.round(
                    edge.confidence_score,
                  )}${edge.contradiction_count ? ` · ⚠${edge.contradiction_count}` : ''}`
              : undefined,
            labelShowBg: true,
            labelBgPadding: [4, 2] as [number, number],
            labelBgBorderRadius: 3,
            labelBgStyle: {
              fill: 'var(--color-panel)',
              fillOpacity: 0.92,
              stroke: 'var(--color-line)',
            },
            labelStyle: { fill: 'var(--color-dim)', fontSize: 10 },
            /*
             * Two channels, one meaning each.
             *
             * Colour is the confidence band and nothing else. Stroke is who
             * stands behind the line: dashed while the engine is merely
             * proposing it, solid once it was confirmed or observed, heavier
             * again when a person drew it themselves.
             *
             * Confirmation deliberately does *not* recolour the edge green.
             * --color-confirmed and --color-band-high are the same value, so
             * a green edge would say "an analyst agreed" and "the engine
             * scored this 50-74" in one stroke, collapsing the distinction
             * this whole interface exists to preserve. Dash to solid is also
             * legible in greyscale, in a screenshot, and to a colourblind
             * reader, none of which green on green is.
             */
            style: {
              stroke: onPath ? 'var(--color-accent)' : color,
              strokeWidth: onPath
                ? 3.5
                : edge.id === selectedEdgeId
                  ? 3
                  : candidate
                    ? 1
                    : asserted
                      ? 2.5
                      : confirmed
                        ? 2.5
                        : 1.5,
              strokeDasharray: candidate
                ? DASH_PROPOSED
                : rejected || contradictory
                  ? DASH_CONTRADICTED
                  : undefined,
              opacity: dimmed ? 0.12 : candidate ? 0.5 : 1,
            },
          }
        }),
    [
      visibleEdges,
      visibleNodeIds,
      selectedEdgeId,
      focusNeighbours,
      highlight,
      labelEveryEdge,
    ],
  )


  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(derivedNodes)
  const [edges, setEdges] = useEdgesState<Edge>(derivedEdges)

  useEffect(() => setNodes(derivedNodes), [derivedNodes, setNodes])
  useEffect(() => setEdges(derivedEdges), [derivedEdges, setEdges])

  // "Reset layout" clears remembered drags and refits the viewport.
  useEffect(() => {
    if (layoutKey > 0) {
      dragged.current = {}
      setNodes(
        derivedNodes.map((node) => ({ ...node, position: { ...node.position } })),
      )
      window.setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 30)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey])

  /*
   * Dragging one node onto another proposes a link. The graph never writes it
   * directly: the analyst has to say why first, and the dialog that asks is
   * the page's business, not this component's.
   */
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return
      if (connection.source === connection.target) return
      onConnectRequest(connection.source, connection.target)
    },
    [onConnectRequest],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange<Node>[]) => {
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          dragged.current[change.id] = change.position
        }
      })
      onNodesChange(changes)
    },
    [onNodesChange],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={handleNodesChange}
      onConnect={handleConnect}
      onNodeClick={(_, node) => onSelectNode(node.id)}
      onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
      onPaneClick={() => {
        onSelectNode(null)
        onSelectEdge(null)
      }}
      fitView
      // Generous padding because the legend, the hint and the minimap all
      // float over the canvas; a tight fit tucks nodes underneath them.
      fitViewOptions={{ padding: 0.32 }}
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      className="bg-void"
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={26}
        size={1}
        color="var(--color-line)"
      />
      <Controls
        showInteractive={false}
        className="rounded-md border border-line bg-panel"
      />
      {/*
        A graph of unconnected cards is confusing unless it says why. Nothing
        has been ruled on yet, so nothing is drawn - and the two ways forward
        are named rather than left to be discovered.

        Bottom-centre, not top: the legend owns the top-left corner and the
        canvas controls the top-right, and this notice was landing on both.
      */}
      {derivedEdges.length === 0 && nodes.length > 0 && (
        <Panel position="bottom-center">
          <div className="mb-2 max-w-[420px] rounded-md border border-line bg-panel/95 px-3 py-2 text-center">
            <div className="panel-title">No connections drawn</div>
            {/*
              With proposals drawn by default this is a much rarer state than
              it used to be, and it means something different: not "nothing is
              confirmed yet" but "nothing was found, or a filter is hiding it
              all". The copy has to say which.
            */}
            <p className="mt-1 text-[11px] leading-snug text-dim">
              {graph.edges.length > 0
                ? 'Every association is hidden by the current filters.'
                : 'Nothing linked these entities to each other. You can still drag one entity onto another to draw a link yourself.'}
            </p>
            {graph.edges.length > 0 && !showCandidates && (
              <p className="mt-1 text-[11px] leading-snug text-faint">
                {graph.edges.length} unreviewed{' '}
                {graph.edges.length === 1 ? 'proposal is' : 'proposals are'}{' '}
                hidden — use “show candidates” to see them.
              </p>
            )}
          </div>
        </Panel>
      )}

      <Panel position="top-left">
        <Legend
          shown={derivedNodes.length}
          total={graph.nodes.length}
          edges={derivedEdges.length}
          showCandidates={showCandidates}
          open={legendOpen}
          onToggle={() => setLegendOpen((value) => !value)}
        />
      </Panel>

      <MiniMap
        pannable
        zoomable
        maskColor="rgba(7, 10, 15, 0.82)"
        nodeColor={(node) => {
          // A throw inside the minimap takes the whole page down with it.
          const data = node.data as EntityNodeData
          return data.node?.confidence_level
            ? CONFIDENCE_COLOR[data.node.confidence_level]
            : '#27384a'
        }}
      />
    </ReactFlow>
  )
}
