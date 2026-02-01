<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate, formatPercent } from '$lib/format';

  type SystemHealthResponse = {
    status?: string;
    uptime_seconds?: number;
  };

  type SystemInfoResponse = {
    info?: {
      python_version?: string;
      lerobot_version?: string;
      percus_ai_version?: string;
    };
  };

  type GpuInfoResponse = {
    gpus?: Array<{ utilization_gpu?: number }>;
  };

  type SystemResourcesResponse = {
    resources?: {
      cpu_percent?: number;
      memory_percent?: number;
      disk_percent?: number;
    };
    timestamp?: string;
  };

  type SystemLogsResponse = {
    logs?: Array<{ level?: string; timestamp?: string; message?: string }>;
  };

  const healthQuery = createQuery<SystemHealthResponse>({
    queryKey: ['system', 'health'],
    queryFn: api.system.health
  });

  const infoQuery = createQuery<SystemInfoResponse>({
    queryKey: ['system', 'info'],
    queryFn: api.system.info
  });

  const gpuQuery = createQuery<GpuInfoResponse>({
    queryKey: ['system', 'gpu'],
    queryFn: api.system.gpu
  });

  const resourcesQuery = createQuery<SystemResourcesResponse>({
    queryKey: ['system', 'resources'],
    queryFn: api.system.resources
  });

  const logsQuery = createQuery<SystemLogsResponse>({
    queryKey: ['system', 'logs'],
    queryFn: api.system.logs
  });

  const refetchAll = () => {
    $healthQuery?.refetch?.();
    $infoQuery?.refetch?.();
    $gpuQuery?.refetch?.();
    $resourcesQuery?.refetch?.();
    $logsQuery?.refetch?.();
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Info</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">システム情報</h1>
      <p class="mt-2 text-sm text-slate-600">環境状態と依存関係を可視化。</p>
    </div>
    <Button.Root class="btn-ghost" type="button" onclick={refetchAll}>再チェック</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-3">
  <div class="card p-6">
    <p class="section-title">Runtime</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">環境</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">Python</p>
        <p class="text-base font-semibold text-slate-800">{$infoQuery.data?.info?.python_version ?? '-'}</p>
      </div>
      <div>
        <p class="label">LeRobot</p>
        <p class="text-base font-semibold text-slate-800">{$infoQuery.data?.info?.lerobot_version ?? '-'}</p>
      </div>
      <div>
        <p class="label">Daihen Physical AI</p>
        <p class="text-base font-semibold text-slate-800">{$infoQuery.data?.info?.percus_ai_version ?? '-'}</p>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Backend</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">API状態</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">Health</p>
        <p class="text-base font-semibold text-slate-800">{$healthQuery.data?.status ?? '-'}</p>
      </div>
      <div>
        <p class="label">Uptime</p>
        <p class="text-base font-semibold text-slate-800">{$healthQuery.data?.uptime_seconds?.toFixed?.(0) ?? '-'} sec</p>
      </div>
      <div>
        <p class="label">GPU 使用率</p>
        <p class="text-base font-semibold text-slate-800">{formatPercent($gpuQuery.data?.gpus?.[0]?.utilization_gpu)}</p>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Resources</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">CPU / メモリ</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">CPU</p>
        <p class="text-base font-semibold text-slate-800">{formatPercent($resourcesQuery.data?.resources?.cpu_percent)}</p>
      </div>
      <div>
        <p class="label">Memory</p>
        <p class="text-base font-semibold text-slate-800">{formatPercent($resourcesQuery.data?.resources?.memory_percent)}</p>
      </div>
      <div>
        <p class="label">Disk</p>
        <p class="text-base font-semibold text-slate-800">{formatPercent($resourcesQuery.data?.resources?.disk_percent)}</p>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">サービスログ</h2>
    <Button.Root class="btn-ghost">エクスポート</Button.Root>
  </div>
  <div class="mt-4 space-y-2 text-xs text-slate-500">
    {#if $logsQuery.isLoading}
      <p>読み込み中...</p>
    {:else if $logsQuery.data?.logs?.length}
      {#each $logsQuery.data.logs as log}
        <p>[{log.level?.toUpperCase?.() ?? 'INFO'}] {formatDate(log.timestamp)} {log.message}</p>
      {/each}
    {:else}
      <p>ログはありません。</p>
    {/if}
  </div>
</section>
