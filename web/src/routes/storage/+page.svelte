<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes } from '$lib/format';

  type DatasetSummary = {
    id: string;
    status?: string;
    size_bytes?: number;
    source?: string;
    dataset_type?: string;
    episode_count?: number;
  };

  type ModelSummary = {
    id: string;
    status?: string;
    size_bytes?: number;
    policy_type?: string;
    dataset_id?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['storage', 'datasets'],
    queryFn: () => api.storage.datasets()
  });

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: ['storage', 'models'],
    queryFn: api.storage.models
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ管理</h1>
      <p class="mt-2 text-sm text-slate-600">データセット・モデル・アーカイブの状況をまとめて確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/archive">アーカイブ一覧</Button.Root>
      <Button.Root class="btn-ghost" href="/storage/usage">ストレージ使用量</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
        <p class="text-xs text-slate-500">最新のデータセットを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost" href="/storage/datasets">管理</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $datasetsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $datasetsQuery.data?.datasets?.length}
        {#each $datasetsQuery.data.datasets.slice(0, 3) as dataset}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="min-w-0 break-all font-semibold text-slate-800">{dataset.id}</span>
              <span class="chip">{dataset.status}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span>size: {formatBytes(dataset.size_bytes)}</span>
              <span>source: {dataset.source ?? 'r2'}</span>
              <span>type: {dataset.dataset_type ?? 'recorded'}</span>
              <span>episodes: {dataset.episode_count ?? 0}</span>
            </div>
          </div>
        {/each}
        {#if $datasetsQuery.data.datasets.length > 3}
          <p class="text-xs text-slate-400">ほか {($datasetsQuery.data.datasets.length - 3)} 件</p>
        {/if}
      {:else}
        <p>データセットがありません。</p>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">モデル管理</h2>
        <p class="text-xs text-slate-500">最新のモデルを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost" href="/storage/models">管理</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $modelsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $modelsQuery.data?.models?.length}
        {#each $modelsQuery.data.models.slice(0, 3) as model}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="min-w-0 break-all font-semibold text-slate-800">{model.id}</span>
              <span class="chip">{model.status}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span>size: {formatBytes(model.size_bytes)}</span>
              <span>policy: {model.policy_type ?? '-'}</span>
              <span>dataset: {model.dataset_id ?? '-'}</span>
            </div>
          </div>
        {/each}
        {#if $modelsQuery.data.models.length > 3}
          <p class="text-xs text-slate-400">ほか {($modelsQuery.data.models.length - 3)} 件</p>
        {/if}
      {:else}
        <p>モデルがありません。</p>
      {/if}
    </div>
  </div>
</section>
