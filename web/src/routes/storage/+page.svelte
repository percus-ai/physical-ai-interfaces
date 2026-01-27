<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes } from '$lib/format';

  const datasetsQuery = createQuery({
    queryKey: ['storage', 'datasets'],
    queryFn: () => api.storage.datasets()
  });

  const modelsQuery = createQuery({
    queryKey: ['storage', 'models'],
    queryFn: api.storage.models
  });

  const usageQuery = createQuery({
    queryKey: ['storage', 'usage'],
    queryFn: api.storage.usage
  });

  const archiveQuery = createQuery({
    queryKey: ['storage', 'archive'],
    queryFn: api.storage.archive
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ管理</h1>
      <p class="mt-2 text-sm text-slate-600">データセット/モデル/アーカイブを統合管理。</p>
    </div>
    <Button.Root class="btn-ghost">ストレージ使用量</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
      <div class="flex gap-2">
        <Button.Root class="btn-ghost">一括操作</Button.Root>
        <Button.Root class="btn-primary">新規追加</Button.Root>
      </div>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $datasetsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $datasetsQuery.data?.datasets?.length}
        {#each $datasetsQuery.data.datasets as dataset}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span>{dataset.id} ({formatBytes(dataset.size_bytes)})</span>
            <span class="chip">{dataset.status}</span>
          </div>
        {/each}
      {:else}
        <p>データセットがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ストレージ使用量</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">データセット</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.datasets_size_bytes)}</p>
      </div>
      <div>
        <p class="label">モデル</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.models_size_bytes)}</p>
      </div>
      <div>
        <p class="label">アーカイブ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.archive_size_bytes)}</p>
      </div>
      <div>
        <p class="label">合計</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.total_size_bytes)}</p>
      </div>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">モデル管理</h2>
      <Button.Root class="btn-ghost">同期</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $modelsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $modelsQuery.data?.models?.length}
        {#each $modelsQuery.data.models as model}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span>{model.id}</span>
            <span class="chip">{model.status}</span>
          </div>
        {/each}
      {:else}
        <p>モデルがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">アーカイブ</h2>
      <Button.Root class="btn-ghost">一覧</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $archiveQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $archiveQuery.data?.datasets?.length || $archiveQuery.data?.models?.length}
        {#each $archiveQuery.data.datasets ?? [] as dataset}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span>{dataset.id}</span>
            <span class="chip">dataset</span>
          </div>
        {/each}
        {#each $archiveQuery.data.models ?? [] as model}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span>{model.id}</span>
            <span class="chip">model</span>
          </div>
        {/each}
      {:else}
        <p>アーカイブは空です。</p>
      {/if}
    </div>
  </div>
</section>
