<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate, formatPercent } from '$lib/format';

  const overviewQuery = createQuery({
    queryKey: ['analytics', 'overview'],
    queryFn: api.analytics.overview
  });

  const systemHealthQuery = createQuery({
    queryKey: ['system', 'health'],
    queryFn: api.system.health
  });

  const resourcesQuery = createQuery({
    queryKey: ['system', 'resources'],
    queryFn: api.system.resources
  });

  const storageUsageQuery = createQuery({
    queryKey: ['storage', 'usage'],
    queryFn: api.storage.usage
  });
</script>

<section class="card-strong p-8">
  <div class="flex flex-wrap items-start justify-between gap-6">
    <div class="space-y-3">
      <p class="section-title">Overview</p>
      <h1 class="text-3xl font-semibold text-slate-900">PerCUs Web Console</h1>
      <p class="max-w-xl text-sm text-slate-600">
        CLIと同等の運用フローをブラウザで再現するための統合コンソールです。各メニューの状態確認と、
        よく使う操作へのショートカットを用意しています。
      </p>
      <div class="flex flex-wrap gap-3">
        <span class="chip">CLI互換フロー</span>
        <span class="chip">SvelteKit + Svelte 5</span>
        <span class="chip">TanStack Query</span>
      </div>
    </div>
    <div class="flex flex-col gap-3">
      <Button.Root class="btn-primary" href="/train">学習ジョブを作成</Button.Root>
      <Button.Root class="btn-ghost" href="/record">録画を開始</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-3">
  <div class="card p-6">
    <p class="section-title">Operate</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">テレオペ / 推論</h2>
    <p class="mt-3 text-sm text-slate-600">テレオペ・推論実行・セッション監視を統合表示。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/operate">開く</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Record</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">録画セッション</h2>
    <p class="mt-3 text-sm text-slate-600">プロジェクト選択、エピソード指定、進行状況を可視化。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/record">開く</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Train</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">学習ジョブ</h2>
    <p class="mt-3 text-sm text-slate-600">新規学習/継続学習、GPU・ストレージ指定を整理。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/train">開く</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <p class="section-title">Recent Activity</p>
    <h3 class="mt-2 text-lg font-semibold text-slate-900">最新の操作ログ</h3>
    {#if $overviewQuery.isLoading}
      <p class="mt-4 text-sm text-slate-500">読み込み中...</p>
    {:else if $overviewQuery.data}
      <div class="mt-4 space-y-3 text-sm text-slate-600">
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <span>プロジェクト数</span>
          <span class="chip">{$overviewQuery.data.stats?.total_projects ?? 0}</span>
        </div>
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <span>エピソード数</span>
          <span class="chip">{$overviewQuery.data.stats?.total_episodes ?? 0}</span>
        </div>
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <span>学習ジョブ数</span>
          <span class="chip">{$overviewQuery.data.stats?.total_training_jobs ?? 0}</span>
        </div>
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <span>モデル数</span>
          <span class="chip">{$overviewQuery.data.stats?.total_models ?? 0}</span>
        </div>
      </div>
    {:else}
      <p class="mt-4 text-sm text-slate-500">データがありません。</p>
    {/if}
  </div>
  <div class="card p-6">
    <p class="section-title">System</p>
    <h3 class="mt-2 text-lg font-semibold text-slate-900">システム状態</h3>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">Backend</p>
        <p class="text-base font-semibold text-slate-800">
          {$systemHealthQuery.data?.status ?? 'unknown'}
        </p>
      </div>
      <div>
        <p class="label">CPU使用率</p>
        <p class="text-base font-semibold text-slate-800">
          {formatPercent($resourcesQuery.data?.resources?.cpu_percent)}
        </p>
      </div>
      <div>
        <p class="label">メモリ使用量</p>
        <p class="text-base font-semibold text-slate-800">
          {formatBytes(($resourcesQuery.data?.resources?.memory_used_gb ?? 0) * 1024 ** 3)} / {formatBytes(($resourcesQuery.data?.resources?.memory_total_gb ?? 0) * 1024 ** 3)}
        </p>
      </div>
      <div>
        <p class="label">ストレージ</p>
        <p class="text-base font-semibold text-slate-800">
          {formatBytes($storageUsageQuery.data?.datasets_size_bytes)}
        </p>
      </div>
      <div class="text-xs text-slate-500">
        更新: {formatDate($resourcesQuery.data?.timestamp)}
      </div>
    </div>
    <div class="mt-6">
      <Button.Root class="btn-ghost" href="/info">詳細</Button.Root>
    </div>
  </div>
</section>
