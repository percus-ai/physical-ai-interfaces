<script lang="ts">
  import SplitPane from '$lib/components/recording/SplitPane.svelte';
  import TabsView from '$lib/components/recording/TabsView.svelte';
  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import type { BlueprintNode } from '$lib/recording/blueprint';
  import { getViewDefinition } from '$lib/recording/viewRegistry';
  import PlaceholderView from '$lib/components/recording/views/PlaceholderView.svelte';

  let {
    node,
    selectedId = '',
    sessionId = '',
    recorderStatus = null,
    rosbridgeStatus = 'idle',
    mode = 'recording',
    editMode = true,
    viewScale = 1,
    onSelect,
    onResize,
    onTabChange
  }: {
    node: BlueprintNode;
    selectedId?: string;
    sessionId?: string;
    recorderStatus?: Record<string, unknown> | null;
    rosbridgeStatus?: 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';
    mode?: 'recording' | 'operate';
    editMode?: boolean;
    viewScale?: number;
    onSelect: (id: string) => void;
    onResize: (id: string, sizes: [number, number]) => void;
    onTabChange: (id: string, activeId: string) => void;
  } = $props();

  const handleSelect = (event: Event) => {
    event.stopPropagation();
    if (editMode) {
      onSelect?.(node.id);
    }
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    handleSelect(event);
  };

  const renderComponent = (viewType: string) => getViewDefinition(viewType)?.component ?? PlaceholderView;

  const buildProps = (viewType: string) => {
    const definition = getViewDefinition(viewType);
    const baseProps = {
      ...(node.type === 'view' ? node.config : {}),
      title: definition?.label ?? viewType,
      mode
    } as Record<string, unknown>;
    if (viewType === 'controls' || viewType === 'progress' || viewType === 'timeline') {
      baseProps.sessionId = sessionId;
      baseProps.recorderStatus = recorderStatus;
      baseProps.rosbridgeStatus = rosbridgeStatus;
    }
    return baseProps;
  };

  const viewType = $derived(node.type === 'view' ? node.viewType : 'placeholder');
  const ViewComponent = $derived(renderComponent(viewType));
  const normalizedViewScale = $derived(Math.min(Math.max(viewScale, 0.25), 1));
  const useVirtualRenderScale = $derived(normalizedViewScale < 0.999);
</script>

<div
  class={`layout-node ${editMode && selectedId === node.id ? 'selected' : ''}`}
  role="button"
  tabindex="0"
  onclick={handleSelect}
  onkeydown={handleKeydown}
>
  {#if node.type === 'split'}
    <SplitPane
      direction={node.direction}
      sizes={node.sizes}
      editable={editMode}
      on:resize={(event) => onResize?.(node.id, event.detail.sizes)}
    >
      {#snippet first()}
        <div class="h-full">
          <LayoutNode
            node={node.children[0]}
            {selectedId}
            {sessionId}
            {recorderStatus}
            {rosbridgeStatus}
            {mode}
            {editMode}
            {viewScale}
            {onSelect}
            {onResize}
            {onTabChange}
          />
        </div>
      {/snippet}
      {#snippet second()}
        <div class="h-full">
          <LayoutNode
            node={node.children[1]}
            {selectedId}
            {sessionId}
            {recorderStatus}
            {rosbridgeStatus}
            {mode}
            {editMode}
            {viewScale}
            {onSelect}
            {onResize}
            {onTabChange}
          />
        </div>
      {/snippet}
    </SplitPane>
  {:else if node.type === 'tabs'}
    <TabsView tabs={node.tabs} activeId={node.activeId} on:change={(event) => onTabChange?.(node.id, event.detail.activeId)}>
      {#each node.tabs as tab (tab.id)}
        {#if tab.id === node.activeId}
          <LayoutNode
            node={tab.child}
            {selectedId}
            {sessionId}
            {recorderStatus}
            {rosbridgeStatus}
            {mode}
            {editMode}
            {viewScale}
            {onSelect}
            {onResize}
            {onTabChange}
          />
        {/if}
      {/each}
    </TabsView>
  {:else}
    <div class="h-full rounded-2xl border border-slate-200/60 bg-white/80 p-3 shadow-sm">
      {#if useVirtualRenderScale}
        <div class="virtual-view">
          <div class="virtual-view-inner" style={`--view-scale:${normalizedViewScale};`}>
            <ViewComponent {...buildProps(viewType)} />
          </div>
        </div>
      {:else}
        <ViewComponent {...buildProps(viewType)} />
      {/if}
    </div>
  {/if}
</div>

<style>
  .layout-node {
    position: relative;
    height: 100%;
    width: 100%;
    min-height: 120px;
  }
  .layout-node.selected > div {
    outline: 2px solid rgba(91, 124, 250, 0.5);
    outline-offset: 2px;
  }
  .virtual-view {
    height: 100%;
    width: 100%;
    overflow: hidden;
  }
  .virtual-view-inner {
    width: calc(100% / var(--view-scale));
    height: calc(100% / var(--view-scale));
    transform: scale(var(--view-scale));
    transform-origin: top left;
  }
</style>
