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
import OrgClusterNode, { type OrgClusterData } from './OrgClusterNode'
import type {
  FilterState,
  GraphNode,
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

const nodeTypes = { entity: EntityNode, orgCluster: OrgClusterNode }

//: Below this, a cluster is more clutter than the nodes it replaces.
const CLUSTER_FROM = 2

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
  clusters,
  showCandidates,
}: {
  shown: number
  total: number
  edges: number
  clusters: number
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
      {clusters > 0 && (
        <div className="mt-1 font-mono text-[10px] text-faint">
          Organizations are grouped by the profile that listed them — click to
          open.
        </div>
      )}
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
  const [openClusters, setOpenClusters] = useState<Set<string>>(new Set())

  /*
   * Organizations, gathered by the profile that listed them.
   *
   * The grouping reads every edge, not just the drawn ones: an organization
   * is an attribute of the profile that published it, and which account
   * listed it does not depend on whether an analyst has ruled on anything.
   */
  const orgGroups = useMemo(() => {
    const parentOf = new Map<string, string>()
    for (const edge of graph.edges) {
      const target = graph.nodes.find((node) => node.id === edge.target)
      if (target?.type === 'ORGANIZATION' && !parentOf.has(edge.target)) {
        parentOf.set(edge.target, edge.source)
      }
    }
    const groups = new Map<string, GraphNode[]>()
    for (const node of graph.nodes) {
      if (node.type !== 'ORGANIZATION') continue
      const parent = parentOf.get(node.id)
      // An organization nothing points at has nothing to collapse into.
      if (!parent) continue
      const members = groups.get(parent) ?? []
      members.push(node)
      groups.set(parent, members)
    }
    // One organization on its own reads better as itself.
    for (const [parent, members] of [...groups]) {
      if (members.length < CLUSTER_FROM) groups.delete(parent)
    }
    return groups
  }, [graph.nodes, graph.edges])

  /** Organization ids currently represented by a collapsed cluster. */
  const collapsedOrgIds = useMemo(() => {
    const hidden = new Set<string>()
    for (const [parent, members] of orgGroups) {
      if (openClusters.has(parent)) continue
      for (const member of members) hidden.add(member.id)
    }
    return hidden
  }, [orgGroups, openClusters])

  /** Edges that survive the current filter set. */
  const visibleEdges = useMemo(
    () =>
      graph.edges.filter((edge) => {
        const established = isEstablished(edge)
        if (!established && !showCandidates) return false
        // A rejected edge is a decision, not a candidate: never redrawn.
        if (edge.analyst_status === 'REJECTED') return false
        if (!filters.relationshipTypes.has(edge.relationship_type)) return false
        /*
         * An analyst-drawn link scores nothing, so the confidence filters
         * would silently erase it. It does not sit on that scale at all -
         * filtering it by a band it was never given would hide the analyst's
         * own work from them.
         */
        if (established && edge.origin === 'ANALYST') return true
        if (!filters.confidenceLevels.has(edge.confidence_level)) return false
        if (edge.confidence_score < filters.minScore) return false
        return true
      }),
    [graph.edges, filters, showCandidates],
  )

  /**
   * Nodes that survive the filters.
   *
   * Every discovered entity stays on the canvas whether or not anything
   * connects it yet. The entity was observed - that is a fact, and it is also
   * what the analyst needs in front of them in order to draw a link to it.
   * The connections are what have to be earned, not the nodes.
   */
  const visibleNodeIds = useMemo(
    () =>
      new Set(
        graph.nodes
          .filter((node) => filters.entityTypes.has(node.type))
          // Members of a collapsed cluster are drawn by the cluster instead.
          .filter((node) => !collapsedOrgIds.has(node.id))
          .map((node) => node.id),
      ),
    [graph.nodes, filters.entityTypes, collapsedOrgIds],
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

  /** One node standing in for each collapsed group of organizations. */
  const clusterNodes = useMemo<Node[]>(() => {
    if (!filters.entityTypes.has('ORGANIZATION')) return []
    const nodes: Node[] = []
    for (const [parentId, members] of orgGroups) {
      const parent = graph.nodes.find((node) => node.id === parentId)
      if (!parent) continue
      const expanded = openClusters.has(parentId)
      const id = `org-cluster:${parentId}`
      // Sit where the group sits, so opening one does not move the canvas.
      const x = members.reduce((sum, m) => sum + m.position.x, 0) / members.length
      const y = members.reduce((sum, m) => sum + m.position.y, 0) / members.length
      nodes.push({
        id,
        type: 'orgCluster',
        position: dragged.current[id] ?? { x, y },
        data: {
          members,
          sourceLabel: parent.label,
          expanded,
          dimmed: focusNeighbours ? !focusNeighbours.has(parentId) : false,
          onToggle: () =>
            setOpenClusters((current) => {
              const next = new Set(current)
              if (next.has(parentId)) next.delete(parentId)
              else next.add(parentId)
              return next
            }),
        } satisfies OrgClusterData,
      })
    }
    return nodes
  }, [orgGroups, openClusters, graph.nodes, filters.entityTypes, focusNeighbours])

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

  /*
   * A cluster hangs off the profile that listed it, and that edge is always
   * drawn. It is not an association between two identities for an analyst to
   * rule on - it is an attribute of one profile, the fact that this page
   * published these names - so the confirm-to-connect rule does not apply to
   * it. It is drawn muted, and never carries a confidence band.
   */
  const clusterEdges = useMemo<Edge[]>(
    () =>
      clusterNodes.map((cluster) => {
        const parentId = cluster.id.slice("org-cluster:".length)
        return {
          id: `${cluster.id}:edge`,
          source: parentId,
          target: cluster.id,
          type: 'smoothstep',
          selectable: false,
          style: {
            stroke: 'var(--color-line-bright)',
            strokeWidth: 1,
            strokeDasharray: '3 4',
          },
        }
      }),
    [clusterNodes],
  )

  const allNodes = useMemo(
    () => [...derivedNodes, ...clusterNodes],
    [derivedNodes, clusterNodes],
  )
  const allEdges = useMemo(
    () => [...derivedEdges, ...clusterEdges],
    [derivedEdges, clusterEdges],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(allNodes)
  const [edges, setEdges] = useEdgesState<Edge>(allEdges)

  useEffect(() => setNodes(allNodes), [allNodes, setNodes])
  useEffect(() => setEdges(allEdges), [allEdges, setEdges])

  // "Reset layout" clears remembered drags and refits the viewport.
  useEffect(() => {
    if (layoutKey > 0) {
      dragged.current = {}
      setNodes(allNodes.map((node) => ({ ...node, position: { ...node.position } })))
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
      onNodeClick={(_, node) => {
        // The cluster handles its own click: it opens, it is not an entity.
        if (node.type === 'orgCluster') return
        onSelectNode(node.id)
      }}
      onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
      onPaneClick={() => {
        onSelectNode(null)
        onSelectEdge(null)
      }}
      fitView
      fitViewOptions={{ padding: 0.25 }}
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
      */}
      {derivedEdges.length === 0 && nodes.length > 0 && (
        <Panel position="top-center">
          <div className="max-w-[420px] rounded-md border border-line bg-panel/95 px-3 py-2 text-center">
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
          shown={derivedNodes.length + collapsedOrgIds.size}
          total={graph.nodes.length}
          edges={derivedEdges.length}
          clusters={clusterNodes.length}
          showCandidates={showCandidates}
        />
      </Panel>

      <MiniMap
        pannable
        zoomable
        maskColor="rgba(7, 10, 15, 0.82)"
        nodeColor={(node) => {
          const data = node.data as EntityNodeData
          return data.node.confidence_level
            ? CONFIDENCE_COLOR[data.node.confidence_level]
            : '#27384a'
        }}
      />
    </ReactFlow>
  )
}
