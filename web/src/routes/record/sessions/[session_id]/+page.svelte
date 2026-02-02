<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import BlueprintTree from '$lib/components/recording/BlueprintTree.svelte';

  import {
    addTab,
    createDefaultBlueprint,
    deleteNode,
    ensureValidSelection,
    findNode,
    removeTab,
    renameTab,
    updateSplitDirection,
    updateSplitSizes,
    updateTabsActive,
    updateViewConfig,
    updateViewType,
    wrapInSplit,
    wrapInTabs,
    type BlueprintNode
  } from '$lib/recording/blueprint';
  import { getViewDefinition, getViewOptions } from '$lib/recording/viewRegistry';

  type ProfileStatusResponse = {
    topics?: string[];
  };

  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    inactive: '停止',
    completed: '完了'
  };

  const sessionId = $derived(page.params.session_id ?? '');

  const topicsQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status'],
    queryFn: api.profiles.activeStatus
  });

  type RecorderStatus = Record<string, unknown> & {
    state?: string;
    status?: string;
    task?: string;
    dataset_id?: string;
    last_error?: string;
  };

  const STATUS_TOPIC = '/lerobot_recorder/status';
  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle');

  let blueprint: BlueprintNode = $state(createDefaultBlueprint());
  let selectedId = $state(blueprint.id);
  let mounted = $state(false);
  let lastSessionId = '';
  let filledDefaults = $state(false);
  let editMode = $state(true);

  const storageKey = (id: string) => `recording-blueprint:${id}`;

  const loadBlueprint = (id: string) => {
    if (typeof localStorage === 'undefined') {
      blueprint = createDefaultBlueprint();
      return;
    }
    const stored = localStorage.getItem(storageKey(id));
    if (stored) {
      try {
        blueprint = JSON.parse(stored) as BlueprintNode;
      } catch {
        blueprint = createDefaultBlueprint();
      }
    } else {
      blueprint = createDefaultBlueprint();
    }
    selectedId = ensureValidSelection(blueprint, selectedId);
  };

  const saveBlueprint = () => {
    if (!mounted || typeof localStorage === 'undefined') return;
    localStorage.setItem(storageKey(sessionId || 'default'), JSON.stringify(blueprint));
  };

  const fillDefaultConfig = (node: BlueprintNode, topics: string[]): BlueprintNode => {
    if (node.type === 'view') {
      const definition = getViewDefinition(node.viewType);
      if (!definition?.defaultConfig) return node;
      const defaults = definition.defaultConfig(topics);
      return {
        ...node,
        config: {
          ...defaults,
          ...node.config
        }
      };
    }
    if (node.type === 'split') {
      return {
        ...node,
        children: [fillDefaultConfig(node.children[0], topics), fillDefaultConfig(node.children[1], topics)]
      };
    }
    return {
      ...node,
      tabs: node.tabs.map((tab) => ({
        ...tab,
        child: fillDefaultConfig(tab.child, topics)
      }))
    };
  };

  onMount(() => {
    mounted = true;
  });

  const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
    if (typeof msg.data === 'string') {
      try {
        return JSON.parse(msg.data) as RecorderStatus;
      } catch {
        return { state: 'unknown' };
      }
    }
    return msg as RecorderStatus;
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(
      STATUS_TOPIC,
      (message) => {
        recorderStatus = parseRecorderPayload(message);
      },
      { throttle_rate: 100 }
    );
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
    });
    rosbridgeStatus = client.getStatus();
    return () => {
      unsubscribe();
      offStatus();
    };
  });

  $effect(() => {
    if (mounted && sessionId && sessionId !== lastSessionId) {
      lastSessionId = sessionId;
      filledDefaults = false;
      loadBlueprint(sessionId);
    }
  });

  $effect(() => {
    if (mounted && sessionId) {
      saveBlueprint();
    }
  });

  $effect(() => {
    if (!filledDefaults && ($topicsQuery.data?.topics ?? []).length > 0) {
      blueprint = fillDefaultConfig(blueprint, $topicsQuery.data?.topics ?? []);
      filledDefaults = true;
    }
  });

  const selectedNode = $derived(selectedId ? findNode(blueprint, selectedId) : null);
  const selectedViewNode = $derived(selectedNode?.type === 'view' ? selectedNode : null);
  const selectedSplitNode = $derived(selectedNode?.type === 'split' ? selectedNode : null);
  const selectedTabsNode = $derived(selectedNode?.type === 'tabs' ? selectedNode : null);

  const updateSelection = (id: string) => {
    selectedId = id;
  };

  const handleResize = (id: string, sizes: [number, number]) => {
    blueprint = updateSplitSizes(blueprint, id, sizes);
  };

  const handleTabChange = (id: string, activeId: string) => {
    blueprint = updateTabsActive(blueprint, id, activeId);
  };

  const handleSplit = (direction: 'row' | 'column') => {
    if (!selectedNode) return;
    blueprint = wrapInSplit(blueprint, selectedNode.id, direction);
  };

  const handleTabs = () => {
    if (!selectedNode) return;
    blueprint = wrapInTabs(blueprint, selectedNode.id);
  };

  const handleViewTypeChange = (nextType: string) => {
    if (!selectedViewNode) return;
    const definition = getViewDefinition(nextType);
    const defaults = definition?.defaultConfig?.($topicsQuery.data?.topics ?? []) ?? {};
    blueprint = updateViewType(blueprint, selectedViewNode.id, nextType);
    blueprint = updateViewConfig(blueprint, selectedViewNode.id, defaults);
  };

  const handleConfigChange = (key: string, value: unknown) => {
    if (!selectedViewNode) return;
    blueprint = updateViewConfig(blueprint, selectedViewNode.id, {
      ...selectedViewNode.config,
      [key]: value
    });
  };

  const handleAddTab = () => {
    if (!selectedTabsNode) return;
    blueprint = addTab(blueprint, selectedTabsNode.id);
  };

  const handleRenameTab = (tabId: string, title: string) => {
    if (!selectedTabsNode) return;
    blueprint = renameTab(blueprint, selectedTabsNode.id, tabId, title);
  };

  const handleRemoveTab = (tabId: string) => {
    if (!selectedTabsNode) return;
    blueprint = removeTab(blueprint, selectedTabsNode.id, tabId);
    selectedId = ensureValidSelection(blueprint, selectedId);
  };

  const handleDeleteSelected = (mode: 'view' | 'split' | 'tabs') => {
    if (!selectedNode) return;
    const message =
      mode === 'view'
        ? 'このビューを削除しますか？'
        : mode === 'split'
          ? 'この分割を解除しますか？（片側のみ残ります）'
          : 'タブセットを解除しますか？（アクティブなタブのみ残ります）';
    if (!confirm(message)) return;
    blueprint = deleteNode(blueprint, selectedNode.id);
    selectedId = ensureValidSelection(blueprint, selectedId);
  };

  const toggleEditMode = () => {
    editMode = !editMode;
  };

  const status = $derived(recorderStatus ?? {});
  const datasetId = $derived((status as RecorderStatus)?.dataset_id ?? sessionId);
  const statusState = $derived((status as RecorderStatus)?.state ?? (status as RecorderStatus)?.status ?? '');
  const statusLabel = $derived(STATUS_LABELS[String(statusState)] ?? String(statusState || 'unknown'));
  const statusDetail = $derived((status as RecorderStatus)?.last_error ?? '');
  const taskLabel = $derived((status as RecorderStatus)?.task ?? '');

  const connectionLabel = $derived(
    rosbridgeStatus === 'connected'
      ? '接続中'
      : rosbridgeStatus === 'connecting'
        ? '接続中...'
        : rosbridgeStatus === 'error'
          ? 'エラー'
          : '切断中'
  );

  const handleReconnect = () => {
    const client = getRosbridgeClient();
    client.connect().catch(() => {
      // ignore; connection status handles UI fallback
    });
  };
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Record Session</p>
      <h1 class="text-3xl font-semibold text-slate-900">録画セッション</h1>
      <p class="mt-2 text-sm text-slate-600">{taskLabel || 'タスク未設定 / 状態を同期中...'}</p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">状態: {statusLabel}</span>
        <span class="chip">接続: {connectionLabel}</span>
        {#if datasetId}
          <span class="chip">Dataset: {datasetId}</span>
        {/if}
      </div>
      {#if rosbridgeStatus !== 'connected'}
        <p class="mt-2 text-xs text-rose-600">rosbridge に接続できません。接続を確認してください。</p>
      {/if}
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" type="button" onclick={toggleEditMode}>
        {editMode ? '閲覧モード' : '編集モード'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/record">録画一覧</Button.Root>
      <Button.Root class="btn-ghost" href="/record/new">新規セッション</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={handleReconnect}>再接続</Button.Root>
    </div>
  </div>
</section>

<section class={`grid gap-6 ${editMode ? 'lg:grid-cols-[260px_minmax(0,1fr)_320px]' : 'lg:grid-cols-[minmax(0,1fr)]'}`}>
  {#if editMode}
    <aside class="card p-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-700">Blueprint</h2>
        <span class="text-[10px] text-slate-400">{selectedNode?.type ?? 'none'}</span>
      </div>
      <div class="mt-3 space-y-3">
        <BlueprintTree node={blueprint} selectedId={selectedId} onSelect={updateSelection} />
      </div>
    </aside>
  {/if}

  <div class="card p-4 min-h-[640px]">
    <LayoutNode
      node={blueprint}
      selectedId={selectedId}
      sessionId={sessionId}
      recorderStatus={recorderStatus}
      rosbridgeStatus={rosbridgeStatus}
      mode="recording"
      editMode={editMode}
      onSelect={updateSelection}
      onResize={handleResize}
      onTabChange={handleTabChange}
    />
  </div>

  {#if editMode}
    <aside class="card p-4">
      <h2 class="text-sm font-semibold text-slate-700">Selection</h2>
      {#if !selectedNode}
        <p class="mt-3 text-xs text-slate-500">選択されていません。</p>
      {:else if selectedNode.type === 'view'}
        <div class="mt-3 space-y-4 text-sm text-slate-700">
          <div>
            <p class="label">View Type</p>
            <select
              class="input mt-2"
              value={selectedViewNode?.viewType}
              on:change={(event) => handleViewTypeChange((event.target as HTMLSelectElement).value)}
            >
              <option value="placeholder">Empty</option>
              {#each getViewOptions() as option}
                <option value={option.type}>{option.label}</option>
              {/each}
            </select>
          </div>

          {#if selectedViewNode}
            {#each getViewDefinition(selectedViewNode.viewType)?.fields ?? [] as field}
              {#if field.type === 'topic'}
                <div>
                  <p class="label">{field.label}</p>
                  <select
                    class="input mt-2"
                    value={(selectedViewNode.config?.[field.key] as string) ?? ''}
                    on:change={(event) => handleConfigChange(field.key, (event.target as HTMLSelectElement).value)}
                  >
                    <option value="">未選択</option>
                    {#each ($topicsQuery.data?.topics ?? []).filter((topic) => field.filter?.(topic) ?? true) as topic}
                      <option value={topic}>{topic}</option>
                    {/each}
                  </select>
                </div>
              {:else if field.type === 'boolean'}
                <label class="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300"
                    checked={Boolean(selectedViewNode.config?.[field.key])}
                    on:change={(event) => handleConfigChange(field.key, (event.target as HTMLInputElement).checked)}
                  />
                  {field.label}
                </label>
              {:else if field.type === 'number'}
                <div>
                  <p class="label">{field.label}</p>
                  <input
                    class="input mt-2"
                    type="number"
                    min="10"
                    value={Number(selectedViewNode.config?.[field.key] ?? 160)}
                    on:change={(event) => handleConfigChange(field.key, Number((event.target as HTMLInputElement).value))}
                  />
                </div>
              {/if}
            {/each}
          {/if}

          <div class="divider"></div>
          <div class="space-y-2">
            <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('row')}>横分割</Button.Root>
            <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('column')}>縦分割</Button.Root>
            <Button.Root class="btn-ghost w-full" type="button" onclick={handleTabs}>タブ化</Button.Root>
            <Button.Root
              class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
              type="button"
              onclick={() => handleDeleteSelected('view')}
            >
              このビューを削除
            </Button.Root>
          </div>
        </div>
      {:else if selectedNode.type === 'split'}
        <div class="mt-3 space-y-4 text-sm text-slate-700">
          <div>
            <p class="label">Direction</p>
            <select
              class="input mt-2"
              value={selectedSplitNode?.direction}
              on:change={(event) => {
                const nextDirection = (event.target as HTMLSelectElement).value as 'row' | 'column';
                if (selectedSplitNode) {
                  blueprint = updateSplitDirection(blueprint, selectedSplitNode.id, nextDirection);
                }
              }}
            >
              <option value="row">横</option>
              <option value="column">縦</option>
            </select>
          </div>
          <p class="text-xs text-slate-500">ドラッグで比率を変更できます。</p>
          <Button.Root
            class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
            type="button"
            onclick={() => handleDeleteSelected('split')}
          >
            分割を解除
          </Button.Root>
        </div>
      {:else if selectedNode.type === 'tabs'}
        <div class="mt-3 space-y-4 text-sm text-slate-700">
          <div class="flex items-center justify-between">
            <p class="label">Tabs</p>
            <Button.Root class="btn-ghost" type="button" onclick={handleAddTab}>タブ追加</Button.Root>
          </div>
          <div class="space-y-2">
            {#each selectedTabsNode?.tabs ?? [] as tab}
              <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
                <input
                  class="input"
                  type="text"
                  value={tab.title}
                  on:change={(event) => handleRenameTab(tab.id, (event.target as HTMLInputElement).value)}
                />
              <Button.Root class="btn-ghost mt-2 w-full" type="button" onclick={() => handleRemoveTab(tab.id)}>
                このタブを削除
              </Button.Root>
            </div>
          {/each}
        </div>
        <Button.Root
          class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
          type="button"
          onclick={() => handleDeleteSelected('tabs')}
        >
          タブセットを解除
        </Button.Root>
      </div>
    {/if}
  </aside>
{/if}
</section>

<section class="card p-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <p class="label">Timeline</p>
      <p class="text-sm font-semibold text-slate-700">再生タイムライン（実装準備）</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" type="button">⏮︎</Button.Root>
      <Button.Root class="btn-primary" type="button">⏯︎</Button.Root>
      <Button.Root class="btn-ghost" type="button">⏭︎</Button.Root>
    </div>
  </div>
  {#if statusDetail}
    <p class="mt-2 text-xs text-slate-500">{statusDetail}</p>
  {/if}
</section>
