<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ArchiveListResponse = {
    datasets?: Array<{ id: string; size_bytes?: number; created_at?: string }>;
    models?: Array<{ id: string; size_bytes?: number; created_at?: string }>;
  };

  const archiveQuery = createQuery<ArchiveListResponse>({
    queryKey: ['storage', 'archive', 'manage'],
    queryFn: api.storage.archive
  });

  const queryClient = useQueryClient();

  let selectedDatasetIds = $state<string[]>([]);
  let selectedModelIds = $state<string[]>([]);
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);

  const datasets = $derived($archiveQuery.data?.datasets ?? []);
  const models = $derived($archiveQuery.data?.models ?? []);
  const selectedCount = $derived(selectedDatasetIds.length + selectedModelIds.length);

  const refetchArchive = async () => {
    await queryClient.invalidateQueries({ queryKey: ['storage', 'archive', 'manage'] });
  };

  async function handleBulkRestore() {
    actionMessage = '';
    actionError = '';

    if (!selectedCount) {
      actionError = '復元対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedCount}件を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.restoreArchive({
        dataset_ids: selectedDatasetIds,
        model_ids: selectedModelIds
      });
      actionMessage = '復元しました。';
      selectedDatasetIds = [];
      selectedModelIds = [];
      await refetchArchive();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleBulkDelete() {
    actionMessage = '';
    actionError = '';

    if (!selectedCount) {
      actionError = '削除対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedCount}件を完全に削除しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.deleteArchive({
        dataset_ids: selectedDatasetIds,
        model_ids: selectedModelIds
      });
      actionMessage = '削除しました。';
      selectedDatasetIds = [];
      selectedModelIds = [];
      await refetchArchive();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '削除に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">アーカイブ一覧</h1>
      <p class="mt-2 text-sm text-slate-600">アーカイブ済みのデータを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchArchive}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">一括操作</h2>
      <p class="text-xs text-slate-500">選択済み: {selectedCount} 件</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        class={`btn-ghost ${selectedCount && !actionLoading ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!selectedCount || actionLoading}
        onclick={handleBulkRestore}
      >
        一括復元
      </button>
      <button
        class={`btn-ghost ${selectedCount && !actionLoading ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!selectedCount || actionLoading}
        onclick={handleBulkDelete}
      >
        一括削除
      </button>
    </div>
  </div>
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $archiveQuery.isLoading}
        <p>読み込み中...</p>
      {:else if datasets.length}
        {#each datasets as dataset}
          <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div class="flex items-center gap-3">
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                bind:group={selectedDatasetIds}
                value={dataset.id}
              />
              <span class="font-semibold text-slate-800">{dataset.id}</span>
            </div>
            <div class="flex items-center gap-2 text-xs text-slate-500">
              <span>{formatBytes(dataset.size_bytes ?? 0)}</span>
              <span>{formatDate(dataset.created_at)}</span>
              <Button.Root class="btn-ghost" href={`/storage/archive/dataset/${dataset.id}`}>詳細</Button.Root>
            </div>
          </div>
        {/each}
      {:else}
        <p>アーカイブ済みデータセットがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">モデル</h2>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $archiveQuery.isLoading}
        <p>読み込み中...</p>
      {:else if models.length}
        {#each models as model}
          <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div class="flex items-center gap-3">
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                bind:group={selectedModelIds}
                value={model.id}
              />
              <span class="font-semibold text-slate-800">{model.id}</span>
            </div>
            <div class="flex items-center gap-2 text-xs text-slate-500">
              <span>{formatBytes(model.size_bytes ?? 0)}</span>
              <span>{formatDate(model.created_at)}</span>
              <Button.Root class="btn-ghost" href={`/storage/archive/model/${model.id}`}>詳細</Button.Root>
            </div>
          </div>
        {/each}
      {:else}
        <p>アーカイブ済みモデルがありません。</p>
      {/if}
    </div>
  </div>
</section>
