import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import CategoryGroupNode, {
  type CategoryGroupNodeData,
} from './CategoryGroupNode'
import ContextMenu from './ContextMenu'
import GraphLegend from './GraphLegend'
import GraphSearch from './GraphSearch'
import GraphToolbar from './GraphToolbar'
import RelationshipEdge, { type RelationshipEdgeData } from './RelationshipEdge'
import SeedNode, { type SeedNodeData } from './SeedNode'
import {
  CARD_WIDTH,
  SEED_HEIGHT,
  SEED_WIDTH,
  categoryHeight,
  investigationToMindMap,
  visibleItems,
  type MindMapItem,
} from './layout/mindMapLayout'
import { anchorFor, calculateInvestigationLayout } from './layout/radialLayout'
import type {
  FilterState,
  InvestigationGraph as GraphPayload,
  PathHighlight,
} from '../../types'
import { CATEGORY_BY_KEY } from './layout/mindMapLayout'

const nodeTypes = { seed: SeedNode, category: CategoryGroupNode }
const edgeTypes = { relationship: RelationshipEdge }

interface Props {
  graph: GraphPayload
  filters: FilterState
  selectedNodeId: string | null
  selectedEdgeId: string | null
  /** A selected path or lead, highlighted over the whole board. */
  highlight: PathHighlight | null
  /** Focus is owned by the page, so the entity panel and the toolbar agree. */
  focusEntityId: string | null
  onFocusChange: (entityId: string | null) => void
  layoutKey: number
  onSelectNode: (id: string | null) => void
  onSelectEdge: (id: string | null) => void
}

/** Sides map to React Flow positions for edge anchoring. */
const SIDE_TO_HANDLE: Record<string, string> = {
  top: 'top',
  right: 'right',
  bottom: 'bottom',
  left: 'left',
}

/**
 * The investigation canvas.
 *
 * Replaces the one-node-per-entity network diagram with an investigation
 * board: a dominant seed, categories of discovered information around it, and
 * curved relationships between the individual entities inside those
 * categories.
 *
 * The backend is untouched — this component reads the same graph payload and
 * regroups it for reading. Selection still resolves to real entity and
 * relationship ids, so the existing panels, evidence and analyst workflow
 * work exactly as before.
 */
export default function InvestigationCanvas({
  graph,
  filters,
  selectedNodeId,
  selectedEdgeId,
  highlight,
  focusEntityId,
  onFocusChange,
  layoutKey,
  onSelectNode,
  onSelectEdge,
}: Props) {
  const { fitView, zoomIn, zoomOut, setCenter } = useReactFlow()
  const dragged = useRef<Record<string, { x: number; y: number }>>({})

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  // Categories the analyst asked to see in full, past the row cap.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [menu, setMenu] = useState<{ item: MindMapItem; x: number; y: number } | null>(
    null,
  )
  const [depthLimit, setDepthLimit] = useState<number | null>(null)

  // -- data ---------------------------------------------------------------

  /** Entities surviving the sidebar filters, before grouping. */
  const filtered = useMemo(() => {
    const nodes = graph.nodes.filter(
      (node) =>
        filters.entityTypes.has(node.type) &&
        !hidden.has(node.id) &&
        (depthLimit === null || node.depth <= depthLimit || node.is_seed),
    )
    const visibleIds = new Set(nodes.map((node) => node.id))
    const edges = graph.edges.filter(
      (edge) =>
        visibleIds.has(edge.source) &&
        visibleIds.has(edge.target) &&
        filters.relationshipTypes.has(edge.relationship_type) &&
        filters.confidenceLevels.has(edge.confidence_level) &&
        edge.confidence_score >= filters.minScore &&
        !(filters.hideRejected && edge.analyst_status === 'REJECTED'),
    )
    return { ...graph, nodes, edges }
  }, [graph, filters, hidden, depthLimit])

  const map = useMemo(() => investigationToMindMap(filtered), [filtered])

  const layout = useMemo(
    () => calculateInvestigationLayout(map.categories, collapsed, expanded),
    [map.categories, collapsed, expanded],
  )

  /** Entities matching the current search. */
  const matched = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return new Set<string>()
    return new Set(
      filtered.nodes
        .filter((node) =>
          [node.label, node.identifier, node.display_name, node.platform_name, node.url]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(term)),
        )
        .map((node) => node.id),
    )
  }, [filtered.nodes, query])

  /** Entities one hop from the focused entity, plus itself. */
  const focusNeighbours = useMemo(() => {
    if (!focusEntityId) return null
    const near = new Set<string>([focusEntityId])
    for (const edge of filtered.edges) {
      if (edge.source === focusEntityId) near.add(edge.target)
      if (edge.target === focusEntityId) near.add(edge.source)
    }
    return near
  }, [focusEntityId, filtered.edges])

  /** Entity ids that should be drawn muted rather than removed. */
  const dimmedEntities = useMemo(() => {
    if (!focusNeighbours && !highlight && !query.trim()) return null
    const dim = new Set<string>()
    for (const node of filtered.nodes) {
      const outOfFocus = focusNeighbours ? !focusNeighbours.has(node.id) : false
      const outOfHighlight = highlight ? !highlight.nodeIds.has(node.id) : false
      const outOfSearch = query.trim() ? !matched.has(node.id) : false
      if (outOfFocus || outOfHighlight || outOfSearch) dim.add(node.id)
    }
    return dim
  }, [filtered.nodes, focusNeighbours, highlight, query, matched])

  // -- canvas nodes -------------------------------------------------------

  const toggleCategory = useCallback((categoryId: string) => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(categoryId)) next.delete(categoryId)
      else next.add(categoryId)
      return next
    })
  }, [])

  const toggleExpanded = useCallback((categoryId: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(categoryId)) next.delete(categoryId)
      else next.add(categoryId)
      return next
    })
  }, [])

  const openContextMenu = useCallback(
    (event: React.MouseEvent, item: MindMapItem) => {
      event.preventDefault()
      event.stopPropagation()
      setMenu({ item, x: event.clientX, y: event.clientY })
    },
    [],
  )

  const derivedNodes = useMemo<Node[]>(() => {
    const nodes: Node[] = []

    if (map.seed) {
      nodes.push({
        id: 'seed',
        type: 'seed',
        position: dragged.current.seed ?? layout.seed,
        selected: selectedNodeId === map.seed.id,
        data: {
          node: map.seed,
          dimmed: dimmedEntities ? dimmedEntities.has(map.seed.id) : false,
          matched: matched.has(map.seed.id),
        } satisfies SeedNodeData,
      })
    }

    for (const category of map.categories) {
      const position = layout.categories.get(category.id)
      if (!position) continue
      nodes.push({
        id: category.id,
        type: 'category',
        position: dragged.current[category.id] ?? position,
        data: {
          category,
          collapsed: collapsed.has(category.id),
          expanded: expanded.has(category.id),
          selectedEntityId: selectedNodeId,
          dimmedItems: dimmedEntities,
          matchedItems: matched,
          onToggle: toggleCategory,
          onToggleExpanded: toggleExpanded,
          onSelectEntity: onSelectNode,
          onItemContextMenu: openContextMenu,
        } satisfies CategoryGroupNodeData,
      })
    }
    return nodes
  }, [
    map,
    layout,
    collapsed,
    expanded,
    selectedNodeId,
    dimmedEntities,
    matched,
    toggleCategory,
    toggleExpanded,
    onSelectNode,
    openContextMenu,
  ])

  // -- canvas edges -------------------------------------------------------

  /**
   * Relationships are stored entity-to-entity but drawn card-to-card, so each
   * endpoint is translated to the canvas node holding it, and to a handle on
   * the individual row when that row is visible.
   */
  const derivedEdges = useMemo<Edge[]>(() => {
    const heightOf = (categoryId: string) => {
      const category = map.categories.find((entry) => entry.id === categoryId)
      return category
        ? categoryHeight(
            category,
            collapsed.has(categoryId),
            expanded.has(categoryId),
          )
        : 0
    }

    /** Entity ids currently rendered as a row with its own handle. */
    const rendered = new Set<string>()
    for (const category of map.categories) {
      if (collapsed.has(category.id)) continue
      for (const item of visibleItems(category, expanded.has(category.id))) {
        rendered.add(item.id)
      }
    }

    const endpoint = (entityId: string, incoming: boolean) => {
      const owner = map.ownerOf.get(entityId)
      if (!owner) return null

      if (owner === 'seed') {
        const side = 'right'
        return {
          node: 'seed',
          handle: incoming ? `seed-${side}-in` : `seed-${side}`,
        }
      }
      // Collapsed, or past the row cap: anchor to the card, not to a handle
      // that is not on the canvas.
      if (collapsed.has(owner) || !rendered.has(entityId)) {
        const position = layout.categories.get(owner)
        const side = position ? anchorFor(position, heightOf(owner)) : 'left'
        return {
          node: owner,
          handle: incoming
            ? `group-${SIDE_TO_HANDLE[side]}-in`
            : `group-${SIDE_TO_HANDLE[side]}`,
        }
      }
      return { node: owner, handle: incoming ? `${entityId}-in` : entityId }
    }

    const edges: Edge[] = []
    for (const edge of filtered.edges) {
      const source = endpoint(edge.source, false)
      const target = endpoint(edge.target, true)
      if (!source || !target) continue
      // An edge between two entities in the same collapsed card would be a
      // loop on the card; there is nothing to show.
      if (source.node === target.node && source.handle === target.handle) continue

      const dimmed =
        (dimmedEntities
          ? dimmedEntities.has(edge.source) || dimmedEntities.has(edge.target)
          : false) || (highlight ? !highlight.edgeIds.has(edge.id) : false)

      edges.push({
        id: edge.id,
        source: source.node,
        target: target.node,
        sourceHandle: source.handle,
        targetHandle: target.handle,
        type: 'relationship',
        selected: edge.id === selectedEdgeId,
        data: {
          edge,
          dimmed,
          // Labels only where they earn their space: the analyst is looking
          // at this edge, or it is one they should not miss.
          showLabel:
            hoveredEdgeId === edge.id ||
            edge.id === selectedEdgeId ||
            edge.analyst_status === 'CONFIRMED' ||
            edge.contradiction_count > 0 ||
            (highlight ? highlight.edgeIds.has(edge.id) : false),
          onHover: setHoveredEdgeId,
        } satisfies RelationshipEdgeData,
      })
    }
    return edges
  }, [
    filtered.edges,
    map,
    layout,
    collapsed,
    expanded,
    selectedEdgeId,
    hoveredEdgeId,
    dimmedEntities,
    highlight,
  ])

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(derivedNodes)
  const [edges, setEdges] = useEdgesState<Edge>(derivedEdges)

  useEffect(() => setNodes(derivedNodes), [derivedNodes, setNodes])
  useEffect(() => setEdges(derivedEdges), [derivedEdges, setEdges])

  /** Analyst drags survive re-renders until the layout is reset. */
  const handleNodesChange = useCallback(
    (changes: NodeChange<Node>[]) => {
      for (const change of changes) {
        if (change.type === 'position' && change.position && !change.dragging) {
          dragged.current[change.id] = change.position
        }
      }
      onNodesChange(changes)
    },
    [onNodesChange],
  )

  // -- framing ------------------------------------------------------------

  useEffect(() => {
    dragged.current = {}
    setCollapsed(new Set())
    setExpanded(new Set())
    setHidden(new Set())
    onFocusChange(null)
    const timer = window.setTimeout(
      () => void fitView({ padding: 0.22, duration: 420 }),
      60,
    )
    return () => window.clearTimeout(timer)
  }, [layoutKey, fitView])

  useEffect(() => {
    const timer = window.setTimeout(
      () => void fitView({ padding: 0.22, duration: 500 }),
      120,
    )
    return () => window.clearTimeout(timer)
  }, [graph.investigation_id, fitView])

  const centreOnSeed = useCallback(() => {
    void setCenter(0, 0, { zoom: 0.95, duration: 400 })
  }, [setCenter])

  const focusMatch = useCallback(() => {
    const first = [...matched][0]
    if (!first) return
    const owner = map.ownerOf.get(first)
    const position =
      owner === 'seed' ? layout.seed : owner ? layout.categories.get(owner) : null
    if (!position) return
    const height = owner === 'seed' ? SEED_HEIGHT : 260
    void setCenter(
      position.x + (owner === 'seed' ? SEED_WIDTH : CARD_WIDTH) / 2,
      position.y + height / 2,
      { zoom: 1.1, duration: 420 },
    )
  }, [matched, map.ownerOf, layout, setCenter])

  const allCollapsed =
    map.categories.length > 0 && collapsed.size === map.categories.length

  const activeCategoryKeys = useMemo(
    () => new Set(map.categories.map((category) => category.key)),
    [map.categories],
  )

  const deeperAvailable = useMemo(
    () =>
      depthLimit !== null &&
      graph.nodes.some((node) => node.depth > depthLimit && !node.is_seed),
    [graph.nodes, depthLimit],
  )

  // Start at depth 1 only when the investigation is large enough that showing
  // everything would defeat the point of grouping it.
  useEffect(() => {
    setDepthLimit(graph.nodes.length > 24 ? 1 : null)
  }, [graph.investigation_id, graph.nodes.length])

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={handleNodesChange}
        onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
        onPaneClick={() => {
          onSelectNode(null)
          onSelectEdge(null)
          setMenu(null)
        }}
        minZoom={0.15}
        maxZoom={2.2}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
        elevateEdgesOnSelect
        defaultEdgeOptions={{ type: 'relationship' }}
      >
        {/* A faint board, not a grid to read against. */}
        <Background
          variant={BackgroundVariant.Dots}
          gap={26}
          size={1}
          color="rgba(148,163,184,0.10)"
        />
        <MiniMap
          pannable
          zoomable
          nodeStrokeWidth={2}
          maskColor="rgba(7,10,15,0.82)"
          style={{
            background: 'rgba(12,17,24,0.94)',
            border: '1px solid var(--color-line)',
            borderRadius: 8,
            height: 108,
            width: 168,
          }}
          nodeColor={(node) =>
            node.type === 'seed'
              ? 'var(--color-accent)'
              : CATEGORY_BY_KEY[
                  (node.data as CategoryGroupNodeData)?.category?.key ?? 'RELATED'
                ]?.accent ?? 'var(--color-line-bright)'
          }
        />
      </ReactFlow>

      <GraphToolbar
        onZoomIn={() => void zoomIn({ duration: 200 })}
        onZoomOut={() => void zoomOut({ duration: 200 })}
        onFitView={() => void fitView({ padding: 0.22, duration: 420 })}
        onResetLayout={() => {
          dragged.current = {}
          setCollapsed(new Set())
          setHidden(new Set())
          onFocusChange(null)
          setNodes(derivedNodes)
          window.setTimeout(
            () => void fitView({ padding: 0.22, duration: 420 }),
            40,
          )
        }}
        onFocusSeed={centreOnSeed}
        onToggleSearch={() => {
          setSearchOpen((open) => !open)
          if (searchOpen) setQuery('')
        }}
        onToggleCollapseAll={() =>
          setCollapsed(
            allCollapsed
              ? new Set()
              : new Set(map.categories.map((category) => category.id)),
          )
        }
        onToggleFocus={() => onFocusChange(focusEntityId ? null : selectedNodeId)}
        searchOpen={searchOpen}
        allCollapsed={allCollapsed}
        focusActive={Boolean(focusEntityId)}
        canFocus={Boolean(selectedNodeId)}
      />

      {searchOpen && (
        <GraphSearch
          value={query}
          matchCount={matched.size}
          onChange={setQuery}
          onSubmit={focusMatch}
          onClose={() => {
            setSearchOpen(false)
            setQuery('')
          }}
        />
      )}

      <GraphLegend activeKeys={activeCategoryKeys} />

      {focusEntityId && (
        <button
          onClick={() => onFocusChange(null)}
          className="absolute left-1/2 top-14 z-20 -translate-x-1/2 rounded border border-accent/60 bg-panel px-3 py-1 font-mono text-[11px] text-accent"
        >
          Focused on one entity · show the whole investigation
        </button>
      )}

      {deeperAvailable && (
        <button
          onClick={() => setDepthLimit((depth) => (depth === null ? null : depth + 1))}
          className="absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded border border-line bg-panel px-3 py-1 font-mono text-[11px] text-dim transition-colors hover:border-accent hover:text-accent"
        >
          Expand {depthLimit === 1 ? '2nd' : `${(depthLimit ?? 1) + 1}th`}-degree
          relationships
        </button>
      )}

      {menu && (
        <ContextMenu
          item={menu.item}
          x={menu.x}
          y={menu.y}
          onOpen={() => onSelectNode(menu.item.id)}
          onFocus={() => {
            onSelectNode(menu.item.id)
            onFocusChange(menu.item.id)
          }}
          onExpand={() => {
            setDepthLimit(null)
            onSelectNode(menu.item.id)
          }}
          onHide={() =>
            setHidden((current) => new Set(current).add(menu.item.id))
          }
          onClose={() => setMenu(null)}
        />
      )}

      {hidden.size > 0 && (
        <button
          onClick={() => setHidden(new Set())}
          className="absolute right-3 top-3 z-20 rounded border border-line bg-panel px-2 py-1 font-mono text-[10px] text-faint transition-colors hover:text-ink"
        >
          {hidden.size} hidden · restore
        </button>
      )}
    </div>
  )
}
