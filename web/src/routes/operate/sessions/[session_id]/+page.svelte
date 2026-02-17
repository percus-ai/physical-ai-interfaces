<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/state';
  import { Button, Tabs } from 'bits-ui';
  import toast from 'svelte-french-toast';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import BlueprintTree from '$lib/components/recording/BlueprintTree.svelte';
  import BlueprintCombobox from '$lib/components/blueprints/BlueprintCombobox.svelte';

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
  import {
    loadBlueprintDraft,
    saveBlueprintDraft,
    type BlueprintSessionKind
  } from '$lib/blueprints/draftStorage';
  import {
    createBlueprintManager,
    type WebuiBlueprintDetail,
    type WebuiBlueprintSummary
  } from '$lib/blueprints/blueprintManager';

  type ProfileStatusResponse = {
    topics?: string[];
  };

  type RunnerStatus = {
    active?: boolean;
    session_id?: string;
    task?: string;
    last_error?: string;
  };

  type InferenceRunnerStatusResponse = {
    runner_status?: RunnerStatus;
  };

  type VlaborStatus = {
    status?: string;
    service?: string;
    state?: string;
    status_detail?: string;
    running_for?: string;
    created_at?: string;
    container_id?: string;
  };

  type OperateStatusStreamPayload = {
    vlabor_status?: VlaborStatus;
    inference_runner_status?: InferenceRunnerStatusResponse;
    operate_status?: unknown;
  };

  const KIND_LABELS: Record<string, string> = {
    inference: '推論',
    teleop: 'テレオペ'
  };

  const sessionId = $derived(page.params.session_id ?? '');
  const sessionKindParam = $derived(page.url.searchParams.get('kind') ?? '');

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>({
    queryKey: ['inference', 'runner', 'status'],
    queryFn: api.inference.runnerStatus
  });

  const vlaborStatusQuery = createQuery<VlaborStatus>({
    queryKey: ['profiles', 'vlabor', 'status'],
    queryFn: api.profiles.vlaborStatus
  });

  const topicsQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'active', 'status'],
    queryFn: api.profiles.activeStatus
  });

  let blueprint: BlueprintNode = $state(createDefaultBlueprint());
  let selectedId = $state('');
  let mounted = $state(false);
  let lastSessionId = '';
  let lastSessionKind = '';
  let filledDefaults = $state(false);
  let editMode = $state(false);
  let editInspectorTab = $state<'blueprint' | 'selection'>('blueprint');
  let editorShellEl = $state<HTMLDivElement | null>(null);
  let editorToolbarEl = $state<HTMLDivElement | null>(null);
  let editorContentEl = $state<HTMLDivElement | null>(null);
  let editorRightPaneWidth = $state(360);
  let editorViewScale = $state(1);

  let activeBlueprintId = $state('');
  let activeBlueprintName = $state('');
  let savedBlueprints = $state<WebuiBlueprintSummary[]>([]);
  let blueprintBusy = $state(false);
  let blueprintActionPending = $state(false);

  const notifyBlueprintError = (message: string) => {
    if (!message || typeof window === 'undefined') return;
    toast.error(message);
  };

  const notifyBlueprintNotice = (message: string) => {
    if (!message || typeof window === 'undefined') return;
    toast.success(message);
  };

  $effect(() => {
    if (!selectedId && blueprint?.id) {
      selectedId = blueprint.id;
    }
  });

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

  const applyBlueprintDetail = (
    detail: WebuiBlueprintDetail,
    useDraft: boolean,
    kind: BlueprintSessionKind
  ) => {
    activeBlueprintId = detail.id;
    activeBlueprintName = detail.name;
    blueprint = detail.blueprint;

    if (useDraft && sessionId) {
      const draft = loadBlueprintDraft(kind, sessionId, detail.id);
      if (draft) {
        blueprint = draft;
      }
    }

    selectedId = ensureValidSelection(blueprint, selectedId);
    filledDefaults = false;
  };

  const blueprintManager = createBlueprintManager({
    getSessionId: () => sessionId,
    getSessionKind: () => blueprintKind,
    getActiveBlueprintId: () => activeBlueprintId,
    getActiveBlueprintName: () => activeBlueprintName,
    getBlueprint: () => blueprint,
    setSavedBlueprints: (items) => {
      savedBlueprints = items;
    },
    setBusy: (value) => {
      blueprintBusy = value;
    },
    setActionPending: (value) => {
      blueprintActionPending = value;
    },
    setError: (message) => {
      notifyBlueprintError(message);
    },
    setNotice: (message) => {
      notifyBlueprintNotice(message);
    },
    applyBlueprintDetail
  });

  const resolveSessionBlueprint = blueprintManager.resolveSessionBlueprint;
  const handleOpenBlueprint = blueprintManager.openBlueprint;
  const handleSaveBlueprint = blueprintManager.saveBlueprint;
  const handleDuplicateBlueprint = blueprintManager.duplicateBlueprint;
  const handleDeleteBlueprint = blueprintManager.deleteBlueprint;
  const handleResetBlueprint = blueprintManager.resetBlueprint;
  const handleSaveBlueprintWithToast = async () => {
    if (typeof window === 'undefined') {
      await handleSaveBlueprint();
      return;
    }
    const loadingToastId = toast.loading('保存中...');
    try {
      await handleSaveBlueprint();
    } finally {
      toast.dismiss(loadingToastId);
    }
  };

  onMount(() => {
    mounted = true;
  });

  let stopOperateStream = () => {};

  onMount(() => {
    stopOperateStream = connectStream<OperateStatusStreamPayload>({
      path: '/api/stream/operate/status',
      onMessage: (payload) => {
        queryClient.setQueryData(['profiles', 'vlabor', 'status'], payload.vlabor_status);
        queryClient.setQueryData(['inference', 'runner', 'status'], payload.inference_runner_status);
        queryClient.setQueryData(['operate', 'status'], payload.operate_status);
      }
    });
  });

  onDestroy(() => {
    stopOperateStream();
  });

  const runnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? {});
  const vlaborStatus = $derived($vlaborStatusQuery.data ?? {});
  const inferenceMatches = $derived(runnerStatus.session_id === sessionId);
  const teleopMatches = $derived(sessionId === 'teleop');

  const resolvedKind = $derived(
    sessionKindParam || (inferenceMatches ? 'inference' : teleopMatches ? 'teleop' : '')
  );
  const blueprintKind = $derived(
    resolvedKind === 'inference' ? 'inference' : resolvedKind === 'teleop' ? 'teleop' : ''
  );

  $effect(() => {
    if (
      mounted &&
      sessionId &&
      blueprintKind &&
      (sessionId !== lastSessionId || blueprintKind !== lastSessionKind)
    ) {
      lastSessionId = sessionId;
      lastSessionKind = blueprintKind;
      void resolveSessionBlueprint();
    }
  });

  $effect(() => {
    if (mounted && sessionId && blueprintKind && activeBlueprintId) {
      saveBlueprintDraft(blueprintKind, sessionId, activeBlueprintId, blueprint);
    }
  });

  $effect(() => {
    if (!filledDefaults && ($topicsQuery.data?.topics ?? []).length > 0) {
      blueprint = fillDefaultConfig(blueprint, $topicsQuery.data?.topics ?? []);
      filledDefaults = true;
      selectedId = ensureValidSelection(blueprint, selectedId);
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

  const recomputeEditorPaneWidth = () => {
    if (typeof window === 'undefined') return;
    if (!editorShellEl || !editorToolbarEl || !editorContentEl) return;
    if (!window.matchMedia('(min-width: 1024px)').matches) {
      editorRightPaneWidth = 360;
      editorViewScale = 1;
      return;
    }

    const shellWidth = editorShellEl.clientWidth;
    const shellHeight = editorShellEl.clientHeight;
    const toolbarHeight = editorToolbarEl.getBoundingClientRect().height;
    const rowGap = Number.parseFloat(window.getComputedStyle(editorShellEl).rowGap || '0') || 0;
    const columnGap = Number.parseFloat(window.getComputedStyle(editorContentEl).columnGap || '0') || 0;
    const contentWidth = editorContentEl.clientWidth;

    if (shellWidth <= 0 || shellHeight <= 0 || contentWidth <= 0) return;

    const viewAspectRatio = shellWidth / shellHeight;
    const editableViewHeight = Math.max(shellHeight - toolbarHeight - rowGap, 1);
    const targetViewWidth = viewAspectRatio * editableViewHeight;
    const computedRightWidth = contentWidth - columnGap - targetViewWidth;
    const nextRightWidth = Math.max(220, computedRightWidth);
    const actualLeftWidth = Math.max(contentWidth - columnGap - nextRightWidth, 1);
    editorRightPaneWidth = nextRightWidth;
    editorViewScale = Math.min(actualLeftWidth / shellWidth, editableViewHeight / shellHeight);
  };

  $effect(() => {
    if (typeof window === 'undefined' || !editMode) return;
    if (!editorShellEl || !editorToolbarEl || !editorContentEl) return;

    const observer = new ResizeObserver(() => {
      recomputeEditorPaneWidth();
    });
    observer.observe(editorShellEl);
    observer.observe(editorToolbarEl);
    observer.observe(editorContentEl);
    const onResize = () => {
      recomputeEditorPaneWidth();
    };
    window.addEventListener('resize', onResize);
    recomputeEditorPaneWidth();

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', onResize);
    };
  });

  const toggleEditMode = () => {
    editMode = !editMode;
    if (editMode) {
      editInspectorTab = 'blueprint';
    }
  };

  const refreshStatus = async () => {
    await Promise.all([
      $inferenceRunnerStatusQuery.refetch?.(),
      $vlaborStatusQuery.refetch?.(),
      $topicsQuery.refetch?.()
    ]);
  };

  const sessionLabel = $derived(KIND_LABELS[resolvedKind] ?? 'セッション');

  const statusLabel = $derived.by(() => {
    if (resolvedKind === 'inference') {
      return inferenceMatches && runnerStatus.active ? '実行中' : '停止';
    }
    if (resolvedKind === 'teleop') {
      return vlaborStatus.status === 'running' ? '実行中' : '停止';
    }
    return '不明';
  });

  const sessionSubtitle = $derived.by(() => {
    if (resolvedKind === 'inference') {
      return runnerStatus.task ?? '';
    }
    if (resolvedKind === 'teleop') {
      const state = vlaborStatus.state ?? vlaborStatus.status ?? '-';
      const runningFor = vlaborStatus.running_for ?? '-';
      return `${state} / running_for: ${runningFor}`;
    }
    return '';
  });
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Operate Session</p>
      <h1 class="text-3xl font-semibold text-slate-900">{sessionLabel} セッション</h1>
      <!-- <p class="mt-2 text-sm text-slate-600">{sessionSubtitle || 'セッション情報を同期中...'}</p>x
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">状態: {statusLabel}</span>
        {#if sessionId}
          <span class="chip">Session: {sessionId}</span>
        {/if}
      </div>
      {#if $inferenceRunnerStatusQuery.isLoading || $vlaborStatusQuery.isLoading}
        <p class="mt-2 text-xs text-slate-500">ステータス取得中...</p>
      {/if} -->
    </div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Button.Root class="btn-ghost" type="button" onclick={toggleEditMode}>
        {editMode ? '閲覧モード' : '編集モード'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/operate">テレオペ / 推論一覧</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={refreshStatus}>更新</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6">
  {#if editMode}
    <div class="card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]">
      <div class="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4" bind:this={editorShellEl}>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3" bind:this={editorToolbarEl}>
          <div class="flex flex-wrap items-end gap-3">
          <div class="min-w-[240px] flex-1">
            <p class="label">保存済みブループリント</p>
            <div class="mt-2">
              <BlueprintCombobox
                items={savedBlueprints}
                value={activeBlueprintId}
                disabled={blueprintBusy || blueprintActionPending || !blueprintKind}
                onSelect={(blueprintId) => {
                  handleOpenBlueprint(blueprintId);
                }}
              />
            </div>
          </div>

          <label class="min-w-[220px] flex-1 text-xs font-semibold text-slate-600">
            <span>名前</span>
            <input class="input mt-1" type="text" bind:value={activeBlueprintName} />
          </label>

          <div class="flex flex-wrap gap-2">
            <Button.Root
              class="btn-primary"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId || !blueprintKind}
              onclick={() => {
                void handleSaveBlueprintWithToast();
              }}
            >
              保存
            </Button.Root>
            <Button.Root
              class="btn-ghost"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId || !blueprintKind}
              onclick={() => {
                handleDuplicateBlueprint();
              }}
            >
              複製
            </Button.Root>
            <Button.Root
              class="btn-ghost"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId || !blueprintKind}
              onclick={() => {
                handleResetBlueprint();
              }}
            >
              リセット
            </Button.Root>
            <Button.Root
              class="btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId || !blueprintKind}
              onclick={() => {
                handleDeleteBlueprint();
              }}
            >
              削除
            </Button.Root>
          </div>
          </div>
          <p class="mt-2 text-[11px] text-slate-500">編集中の内容はローカルに自動保存されます。</p>

        </div>

        <div
          class="min-h-0 grid gap-4 lg:grid-cols-[minmax(0,1fr)_var(--editor-right-pane-width)]"
          style={`--editor-right-pane-width:${Math.round(editorRightPaneWidth)}px;`}
          bind:this={editorContentEl}
        >
        <div class="min-h-0 rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <LayoutNode
            node={blueprint}
            selectedId={selectedId}
            sessionId={sessionId}
            mode="operate"
            editMode={editMode}
            viewScale={editorViewScale}
            onSelect={updateSelection}
            onResize={handleResize}
            onTabChange={handleTabChange}
          />
        </div>

        <aside class="min-h-0 rounded-xl border border-slate-200/60 bg-white/70 p-3 lg:overflow-y-auto">
          <Tabs.Root bind:value={editInspectorTab}>
            <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
              <Tabs.Trigger
                value="blueprint"
                class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
              >
                Blueprint
              </Tabs.Trigger>
              <Tabs.Trigger
                value="selection"
                class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
              >
                Selection
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="blueprint" class="mt-3">
              <BlueprintTree node={blueprint} selectedId={selectedId} onSelect={updateSelection} />
            </Tabs.Content>

            <Tabs.Content value="selection" class="mt-3">
              {#if !selectedNode}
                <p class="text-xs text-slate-500">選択されていません。</p>
              {:else if selectedNode.type === 'view'}
                <div class="space-y-4 text-sm text-slate-700">
              <div>
                <p class="label">View Type</p>
                <select
                  class="input mt-2"
                  value={selectedViewNode?.viewType}
                  onchange={(event) => handleViewTypeChange((event.target as HTMLSelectElement).value)}
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
                        onchange={(event) => handleConfigChange(field.key, (event.target as HTMLSelectElement).value)}
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
                        onchange={(event) => handleConfigChange(field.key, (event.target as HTMLInputElement).checked)}
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
                        onchange={(event) => handleConfigChange(field.key, Number((event.target as HTMLInputElement).value))}
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
                <div class="space-y-4 text-sm text-slate-700">
              <div>
                <p class="label">Direction</p>
                <select
                  class="input mt-2"
                  value={selectedSplitNode?.direction}
                  onchange={(event) => {
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
                <div class="space-y-4 text-sm text-slate-700">
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
                      onchange={(event) => handleRenameTab(tab.id, (event.target as HTMLInputElement).value)}
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
            </Tabs.Content>
          </Tabs.Root>
        </aside>
      </div>
    </div>
    </div>
  {:else}
    <div class="card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]">
      <LayoutNode
        node={blueprint}
        selectedId={selectedId}
        sessionId={sessionId}
        mode="operate"
        editMode={editMode}
        viewScale={1}
        onSelect={updateSelection}
        onResize={handleResize}
        onTabChange={handleTabChange}
      />
    </div>
  {/if}
</section>
