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
      <p class="mt-2 text-sm text-slate-600">データセット・モデル・アーカイブの状況をまとめて確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost">アーカイブ一覧</Button.Root>
      <Button.Root class="btn-ghost">ストレージ使用量</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
        <p class="text-xs text-slate-500">最新のデータセットを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost">管理</Button.Root>
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

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ストレージ使用量</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">データセット</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.datasets_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.datasets_count ?? 0}</p>
      </div>
      <div>
        <p class="label">モデル</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.models_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.models_count ?? 0}</p>
      </div>
      <div>
        <p class="label">アーカイブ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.archive_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.archive_count ?? 0}</p>
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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">モデル管理</h2>
        <p class="text-xs text-slate-500">最新のモデルを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost">管理</Button.Root>
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

  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">アーカイブ一覧</h2>
        <p class="text-xs text-slate-500">アーカイブ済みのデータを表示</p>
      </div>
      <Button.Root class="btn-ghost">管理</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $archiveQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $archiveQuery.data?.datasets?.length || $archiveQuery.data?.models?.length}
        <div class="space-y-2">
          {#each ($archiveQuery.data.datasets ?? []).slice(0, 2) as dataset}
            <div class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
              <span class="min-w-0 break-all">📁 {dataset.id}</span>
              <span class="chip">dataset</span>
            </div>
          {/each}
          {#each ($archiveQuery.data.models ?? []).slice(0, 2) as model}
            <div class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
              <span class="min-w-0 break-all">🤖 {model.id}</span>
              <span class="chip">model</span>
            </div>
          {/each}
        </div>
        {#if ($archiveQuery.data.datasets?.length ?? 0) + ($archiveQuery.data.models?.length ?? 0) > 4}
          <p class="text-xs text-slate-400">ほか {($archiveQuery.data.datasets?.length ?? 0) + ($archiveQuery.data.models?.length ?? 0) - 4} 件</p>
        {/if}
      {:else}
        <p>アーカイブは空です。</p>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">HuggingFace連携</h2>
        <p class="text-xs text-slate-500">HuggingFace との入出力を管理</p>
      </div>
    </div>
    <div class="mt-4 grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
      <Button.Root class="btn-card w-full" href="/storage/huggingface/import-dataset">
        📥 データセットをインポート
        <span class="text-xs text-slate-400">repo_id → project/dataset</span>
      </Button.Root>
      <Button.Root class="btn-card w-full" href="/storage/huggingface/import-model">
        📥 モデルをインポート
        <span class="text-xs text-slate-400">repo_id → project/model</span>
      </Button.Root>
      <Button.Root class="btn-card w-full" href="/storage/huggingface/export-dataset">
        📤 データセットをエクスポート
        <span class="text-xs text-slate-400">dataset → repo_id</span>
      </Button.Root>
      <Button.Root class="btn-card w-full" href="/storage/huggingface/export-model">
        📤 モデルをエクスポート
        <span class="text-xs text-slate-400">model → repo_id</span>
      </Button.Root>
    </div>
  </div>

  <div class="card p-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold text-slate-900">データ管理メモ</h2>
        <p class="text-xs text-slate-500">運用フローのメモ</p>
      </div>
    </div>
    <div class="mt-4 space-y-2 text-sm text-slate-600">
      <p>・データセット一覧は active のみ表示</p>
      <p>・一括メニューはマージ/アーカイブを想定</p>
      <p>・アーカイブは dataset/model を統合表示</p>
      <p>・HuggingFace連携は操作UIを後段で追加</p>
    </div>
  </div>
</section>
