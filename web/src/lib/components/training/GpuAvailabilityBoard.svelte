<script lang="ts">
  import type { GpuAvailabilityItem } from '$lib/types/training';

  let {
    items = [],
    loading = false,
    selectedGpuModel = '',
    selectedGpuCount = undefined,
    showOnlyAvailableDefault = true,
    preferredModelOrder = []
  }: {
    items?: GpuAvailabilityItem[];
    loading?: boolean;
    selectedGpuModel?: string;
    selectedGpuCount?: number;
    showOnlyAvailableDefault?: boolean;
    preferredModelOrder?: string[];
  } = $props();

  const isAvailable = (item: GpuAvailabilityItem) =>
    Boolean(item.spot_available || item.ondemand_available);

  const locationCount = (locations?: string[]) => locations?.length ?? 0;

  const formatSpotPrice = (value?: number | null) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '-';
    return `$${value.toFixed(3)}/h`;
  };

  const statusClass = (available?: boolean) =>
    available
      ? 'border border-emerald-200/70 bg-emerald-100 text-emerald-700'
      : 'border border-slate-200/70 bg-slate-100 text-slate-500';

  const isSelected = (item: GpuAvailabilityItem) =>
    Boolean(
      selectedGpuModel &&
        selectedGpuCount !== undefined &&
        item.gpu_model === selectedGpuModel &&
        item.gpu_count === selectedGpuCount
    );

  let showUnavailable = $state(false);
  let initializedShowUnavailable = $state(false);
  let expandedModels = $state<string[]>([]);

  $effect(() => {
    if (initializedShowUnavailable) return;
    showUnavailable = !showOnlyAvailableDefault;
    initializedShowUnavailable = true;
  });

  const totalCount = $derived(items.length);
  const availableCount = $derived(items.filter(isAvailable).length);
  const unavailableCount = $derived(totalCount - availableCount);

  const visibleItems = $derived(
    showUnavailable ? items : items.filter(isAvailable)
  );

  const orderedModelNames = $derived.by(() => {
    const models = new Set(visibleItems.map((item) => item.gpu_model));
    const preferred = preferredModelOrder.filter((model) => models.has(model));
    const knownModels = new Set(preferred);
    const rest = [...models]
      .filter((model) => !knownModels.has(model))
      .sort((a, b) => a.localeCompare(b));
    return [...preferred, ...rest];
  });

  const groupedModels = $derived(
    orderedModelNames.map((modelName) => ({
      modelName,
      entries: visibleItems
        .filter((item) => item.gpu_model === modelName)
        .slice()
        .sort(
          (a, b) =>
            a.gpu_count - b.gpu_count ||
            a.instance_type.localeCompare(b.instance_type)
        ),
      availableEntries: visibleItems.filter(
        (item) => item.gpu_model === modelName && isAvailable(item)
      ).length
    }))
  );

  const isExpanded = (modelName: string) => expandedModels.includes(modelName);

  const toggleExpanded = (modelName: string) => {
    if (isExpanded(modelName)) {
      expandedModels = expandedModels.filter((name) => name !== modelName);
      return;
    }
    expandedModels = [...expandedModels, modelName];
  };
</script>

<div class="space-y-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap gap-2">
      <span class="chip">総数 {totalCount}</span>
      <span class="chip border border-emerald-200/70 bg-emerald-100 text-emerald-700">
        利用可能 {availableCount}
      </span>
      <span class="chip border border-slate-200/70 bg-slate-100 text-slate-500">
        利用不可 {unavailableCount}
      </span>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <button
        class="btn-ghost !px-3 !py-1.5 text-xs"
        type="button"
        onclick={() => (showUnavailable = !showUnavailable)}
      >
        {showUnavailable ? '利用不可を隠す' : '利用不可も表示'}
      </button>
      <button
        class="btn-ghost !px-3 !py-1.5 text-xs"
        type="button"
        onclick={() => (expandedModels = [])}
        disabled={!expandedModels.length}
      >
        全て折りたたむ
      </button>
    </div>
  </div>

  {#if loading}
    <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4 text-sm text-slate-500">
      GPU空き状況を読み込み中...
    </div>
  {:else if !visibleItems.length}
    <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4 text-sm text-slate-500">
      {#if showUnavailable}
        GPU構成の情報がありません。
      {:else}
        利用可能な構成はありません。必要であれば「利用不可も表示」を有効にしてください。
      {/if}
    </div>
  {:else}
    <div class="space-y-3">
      {#each groupedModels as group}
        <section class="rounded-2xl border border-slate-200/70 bg-white/70">
          <button
            class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            type="button"
            onclick={() => toggleExpanded(group.modelName)}
          >
            <div class="min-w-0">
              <p class="text-sm font-semibold text-slate-900">{group.modelName}</p>
              <p class="mt-0.5 text-xs text-slate-500">
                {group.entries.length} 構成 / 利用可能 {group.availableEntries}
              </p>
            </div>
            <span class="chip">{isExpanded(group.modelName) ? '折りたたむ' : '展開'}</span>
          </button>

          {#if isExpanded(group.modelName)}
            <div class="border-t border-slate-200/70 px-3 py-2">
              <div class="space-y-2">
                {#each group.entries as item}
                  <div
                    class={`rounded-xl border px-3 py-2 transition ${
                      isSelected(item)
                        ? 'border-brand/40 bg-brand/5 ring-2 ring-brand/20'
                        : 'border-slate-200/60 bg-white/80'
                    }`}
                  >
                    <div class="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p class="text-sm font-semibold text-slate-800">x{item.gpu_count}</p>
                        <p class="text-xs text-slate-500">{item.instance_type}</p>
                      </div>
                      <div class="flex flex-wrap items-center gap-2 text-xs">
                        <span class={`rounded-full px-2.5 py-1 font-semibold ${statusClass(item.spot_available)}`}>
                          Spot {item.spot_available ? '可' : '不可'}
                        </span>
                        <span class={`rounded-full px-2.5 py-1 font-semibold ${statusClass(item.ondemand_available)}`}>
                          On-demand {item.ondemand_available ? '可' : '不可'}
                        </span>
                      </div>
                    </div>
                    <div class="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
                      <p>Spot価格: <span class="font-semibold text-slate-700">{formatSpotPrice(item.spot_price_per_hour)}</span></p>
                      <p>Spot拠点: <span class="font-semibold text-slate-700">{locationCount(item.spot_locations)}</span></p>
                      <p>On-demand拠点: <span class="font-semibold text-slate-700">{locationCount(item.ondemand_locations)}</span></p>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </section>
      {/each}
    </div>
  {/if}
</div>
