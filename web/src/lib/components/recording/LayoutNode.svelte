<script lang="ts">
  import SplitPane from '$lib/components/recording/SplitPane.svelte';
  import TabsView from '$lib/components/recording/TabsView.svelte';
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
    onSelect: (id: string) => void;
    onResize: (id: string, sizes: [number, number]) => void;
    onTabChange: (id: string, activeId: string) => void;
  } = $props();

  const handleSelect = (event: MouseEvent) => {
    event.stopPropagation();
    if (editMode) {
      onSelect?.(node.id);
    }
  };

  const renderComponent = (viewType: string) => getViewDefinition(viewType)?.component ?? PlaceholderView;

  const buildProps = (viewType: string) => {
    const definition = getViewDefinition(viewType);
    const baseProps = {
      ...(node.type === 'view' ? node.config : {}),
      title: definition?.label ?? viewType,
      mode
    } as Record<string, unknown>;
    if (viewType === 'controls' || viewType === 'progress') {
      baseProps.sessionId = sessionId;
      baseProps.recorderStatus = recorderStatus;
      baseProps.rosbridgeStatus = rosbridgeStatus;
    }
    return baseProps;
  };
</script>

<div class={`layout-node ${editMode && selectedId === node.id ? 'selected' : ''}`} on:click={handleSelect}>
  {#if node.type === 'split'}
    <SplitPane
      direction={node.direction}
      sizes={node.sizes}
      editable={editMode}
      on:resize={(event) => onResize?.(node.id, event.detail.sizes)}
    >
      <div slot="first" class="h-full">
        <svelte:self
          node={node.children[0]}
          {selectedId}
          {sessionId}
          {editMode}
          {onSelect}
          {onResize}
          {onTabChange}
        />
      </div>
      <div slot="second" class="h-full">
        <svelte:self
          node={node.children[1]}
          {selectedId}
          {sessionId}
          {editMode}
          {onSelect}
          {onResize}
          {onTabChange}
        />
      </div>
    </SplitPane>
  {:else if node.type === 'tabs'}
    <TabsView tabs={node.tabs} activeId={node.activeId} on:change={(event) => onTabChange?.(node.id, event.detail.activeId)}>
      {#each node.tabs as tab (tab.id)}
        {#if tab.id === node.activeId}
          <svelte:self
            node={tab.child}
            {selectedId}
            {sessionId}
            {editMode}
            {onSelect}
            {onResize}
            {onTabChange}
          />
        {/if}
      {/each}
    </TabsView>
  {:else}
    <div class="h-full rounded-2xl border border-slate-200/60 bg-white/80 p-3 shadow-sm">
      <svelte:component this={renderComponent(node.viewType)} {...buildProps(node.viewType)} />
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
</style>
