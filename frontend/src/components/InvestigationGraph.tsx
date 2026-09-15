import { useCallback, useEffect, useMemo, useRef } from 'react'
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
} from '../types'
import {
  ASSERTED_COLOR,
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  CONFIDENCE_ORDER,
} from '../lib/display'

/**
 * Whether an edge has been established rather than merely proposed.
 *
 * The graph draws connections an analyst stands behind: one they confirmed,
 * or one they drew themselves. Everything else is a candidate the engine has
 * put forward, and lives in the results list until it is ruled on.
 */
function isEstablished(edge: GraphPayload['edges'][number]): boolean {
  return edge.analyst_status === 'CONFIRMED' || edge.origin === 'ANALYST'
}

const nodeTypes = { entity: EntityNode }

/**
 * What the drawing means.
 *
 * Colour is confidence and nothing else, so it needs saying once, on the
 * canvas, rather than in documentation the analyst will not have open.
 */
function Legend({
  shown,
  total,
  edges,
  showCandidates,
}: {
  shown: number
  total: number
  edges: number
  showCandidates: boolean
}) {
  return (
    <div className="rounded-md border border-line bg-panel/95 px-2.5 py-2">
      <div className="panel-title mb-1.5">Confidence</div>
      <ul className="space-y-1">
        {CONFIDENCE_ORDER.map((level) => (
          <li key={level} className="flex items-center gap-1.5 font-mono text-[10px]">
            <span
              className="h-[2px] w-4 shrink-0 rounded"
              style={{ background: CONFIDENCE_COLOR[level] }}
            />
            <span className="text-dim">{CONFIDENCE_LABEL[level]}</span>
          </li>
        ))}
        <li className="flex items-center gap-1.5 font-mono text-[10px]">
          <span
            className="h-0 w-4 shrink-0 border-t border-dashed"
            style={{ borderColor: 'var(--color-contradiction)' }}
          />
          <span className="text-dim">Contradicted</span>
        </li>
        <li className="flex items-center gap-1.5 font-mono text-[10px]">
          <span
            className="h-[2px] w-4 shrink-0 rounded"
            style={{ background: ASSERTED_COLOR }}
          />
          <span className="text-dim">Asserted by you</span>
        </li>
        {showCandidates && (
          <li className="flex items-center gap-1.5 font-mono text-[10px]">
            <span
              className="h-0 w-4 shrink-0 border-t border-dotted"
              style={{ borderColor: 'var(--color-faint)' }}
            />
            <span className="text-faint">Candidate, not yet ruled on</span>
          </li>
        )}
      </ul>
      <div className="mt-1.5 border-t border-line pt-1.5 font-mono text-[10px] text-faint">
        A dashed node was referenced but never read.
      </div>
      <div className="mt-1 font-mono text-[10px] text-faint">
        {shown} of {total} entities · {edges}{' '}
        {edges === 1 ? 'connection' : 'connections'}
      </div>
    </div>
  )
}

interface Props {
  graph: GraphPayload
  filters: FilterState
  /**
   * Draw the unreviewed candidates too, faintly. Off by default: the point of
   * this canvas is the picture the analyst has built, not everything the
   * engine proposed.
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
          // Proposed by the engine, not yet ruled on: shown only when the
          // analyst asks to see candidates, and drawn so it cannot be
          // mistaken for something they have accepted.
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
            type: 'smoothstep',
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
            style: {
              stroke: onPath ? 'var(--color-accent)' : color,
              strokeWidth: onPath
                ? 3.5
                : edge.id === selectedEdgeId
                  ? 3
                  : candidate
                    ? 1
                    : asserted
                      ? 2
                      : 1.5,
              strokeDasharray: candidate
                ? '2 5'
                : rejected || contradictory
                  ? '5 4'
                  : undefined,
              opacity: dimmed ? 0.12 : candidate ? 0.45 : 1,
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
            <div className="panel-title">No connections drawn yet</div>
            <p className="mt-1 text-[11px] leading-snug text-dim">
              This canvas shows the links you stand behind. Confirm an
              association in the results list and it appears here — or drag one
              entity onto another to draw the link yourself.
            </p>
            <p className="mt-1 text-[11px] leading-snug text-faint">
              {graph.edges.length > 0 &&
                `${graph.edges.length} candidate${
                  graph.edges.length === 1 ? '' : 's'
                } are waiting to be reviewed.`}
            </p>
          </div>
        </Panel>
      )}

      <Panel position="top-left">
        <Legend
          shown={derivedNodes.length}
          total={graph.nodes.length}
          edges={derivedEdges.length}
          showCandidates={showCandidates}
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
