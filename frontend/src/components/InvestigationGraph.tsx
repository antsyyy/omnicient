import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
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
import { CONFIDENCE_COLOR } from '../lib/display'

const nodeTypes = { entity: EntityNode }

interface Props {
  graph: GraphPayload
  filters: FilterState
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

  /** Edges that survive the current filter set. */
  const visibleEdges = useMemo(
    () =>
      graph.edges.filter((edge) => {
        if (!filters.relationshipTypes.has(edge.relationship_type)) return false
        if (!filters.confidenceLevels.has(edge.confidence_level)) return false
        if (edge.confidence_score < filters.minScore) return false
        if (filters.hideRejected && edge.analyst_status === 'REJECTED') return false
        return true
      }),
    [graph.edges, filters],
  )

  /** Nodes that survive the filters, keeping the seed visible at all times. */
  const visibleNodeIds = useMemo(() => {
    const connected = new Set<string>()
    visibleEdges.forEach((edge) => {
      connected.add(edge.source)
      connected.add(edge.target)
    })
    return new Set(
      graph.nodes
        .filter(
          (node) =>
            filters.entityTypes.has(node.type) && (node.is_seed || connected.has(node.id)),
        )
        .map((node) => node.id),
    )
  }, [graph.nodes, visibleEdges, filters.entityTypes])

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
          const onPath = highlight ? highlight.edgeIds.has(edge.id) : false
          const dimmed =
            (focusNeighbours
              ? !(focusNeighbours.has(edge.source) && focusNeighbours.has(edge.target))
              : false) ||
            (highlight ? !onPath : false)
          const color = rejected
            ? 'var(--color-rejected)'
            : contradictory
              ? 'var(--color-contradiction)'
              : CONFIDENCE_COLOR[edge.confidence_level]
          return {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            selected: edge.id === selectedEdgeId,
            animated: edge.relationship_type === 'POTENTIAL_SAME_IDENTITY',
            label: `${edge.relationship_label} · ${Math.round(edge.confidence_score)}${
              edge.contradiction_count ? ` · ⚠${edge.contradiction_count}` : ''
            }`,
            labelShowBg: true,
            labelBgPadding: [4, 2] as [number, number],
            labelBgBorderRadius: 3,
            style: {
              stroke: onPath ? 'var(--color-accent)' : color,
              strokeWidth: onPath ? 3.5 : edge.id === selectedEdgeId ? 3 : 1.5,
              strokeDasharray: rejected || contradictory ? '5 4' : undefined,
              opacity: dimmed ? 0.12 : 1,
            },
          }
        }),
    [visibleEdges, visibleNodeIds, selectedEdgeId, focusNeighbours, highlight],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(derivedNodes)
  const [edges, setEdges] = useEdgesState<Edge>(derivedEdges)

  useEffect(() => setNodes(derivedNodes), [derivedNodes, setNodes])
  useEffect(() => setEdges(derivedEdges), [derivedEdges, setEdges])

  // "Reset layout" clears remembered drags and refits the viewport.
  useEffect(() => {
    if (layoutKey > 0) {
      dragged.current = {}
      setNodes(derivedNodes.map((node) => ({ ...node, position: { ...node.position } })))
      window.setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 30)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey])

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
      onNodeClick={(_, node) => onSelectNode(node.id)}
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
