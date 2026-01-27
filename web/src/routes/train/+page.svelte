<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate } from '$lib/format';
  import { GPU_MODELS, POLICY_TYPES } from '$lib/policies';

  const datasetsQuery = createQuery({
    queryKey: ['storage', 'datasets'],
    queryFn: () => api.storage.datasets()
  });

  const jobsQuery = createQuery({
    queryKey: ['training', 'jobs'],
    queryFn: api.training.jobs
  });

  const gpuAvailabilityQuery = createQuery({
    queryKey: ['training', 'gpu-availability'],
    queryFn: api.training.gpuAvailability
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル学習</h1>
      <p class="mt-2 text-sm text-slate-600">
        CLIのPOLICY_TYPESに準拠したポリシー一覧と、学習ジョブの状態を確認します。
      </p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary">新規学習</Button.Root>
      <Button.Root class="btn-ghost">継続学習</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1fr_1fr]">
  <div class="card p-6">
    <h3 class="text-lg font-semibold text-slate-900">ポリシー候補 (CLI基準)</h3>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#each POLICY_TYPES as policy}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <div class="flex items-center justify-between">
            <p class="font-semibold text-slate-800">{policy.displayName}</p>
            <span class="chip">{policy.id}</span>
          </div>
          <p class="mt-2 text-xs text-slate-500">
            steps: {policy.defaultSteps} / batch: {policy.defaultBatchSize} / save: {policy.defaultSaveFreq}
          </p>
        </div>
      {/each}
    </div>
  </div>

  <div class="card p-6">
    <h3 class="text-lg font-semibold text-slate-900">データセット候補</h3>
    <div class="mt-4 space-y-2 text-sm text-slate-600">
      {#if $datasetsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $datasetsQuery.data?.datasets?.length}
        {#each $datasetsQuery.data.datasets as dataset}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
            <span>{dataset.id}</span>
            <span class="chip">{dataset.status}</span>
          </div>
        {/each}
      {:else}
        <p>データセットがありません。</p>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1fr_1fr]">
  <div class="card p-6">
    <h3 class="text-lg font-semibold text-slate-900">GPU 空き状況 (Verda)</h3>
    <div class="mt-4 space-y-2 text-sm text-slate-600">
      {#if $gpuAvailabilityQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $gpuAvailabilityQuery.data?.available?.length}
        {#each $gpuAvailabilityQuery.data.available as gpu}
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
            <span class="font-semibold text-slate-800">{gpu.gpu_model} x {gpu.gpu_count}</span>
            <span class="chip">{gpu.spot_available ? 'Spot可' : 'Spot不可'}</span>
            <span class="chip">{gpu.ondemand_available ? 'On-demand可' : 'On-demand不可'}</span>
          </div>
        {/each}
      {:else}
        <p>GPU 情報がありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h3 class="text-lg font-semibold text-slate-900">GPU モデル (CLI基準)</h3>
    <div class="mt-4 space-y-2 text-sm text-slate-600">
      {#each GPU_MODELS as gpu}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
          <p class="font-semibold text-slate-800">{gpu.name}</p>
          <p class="text-xs text-slate-500">{gpu.description}</p>
        </div>
      {/each}
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 space-y-3 text-sm text-slate-600">
    {#if $jobsQuery.isLoading}
      <p>読み込み中...</p>
    {:else if $jobsQuery.data?.jobs?.length}
      {#each $jobsQuery.data.jobs as job}
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <div>
            <p class="font-semibold text-slate-800">{job.job_name}</p>
            <p class="text-xs text-slate-500">{job.dataset_id ?? '-'} / {job.policy_type ?? '-'}</p>
          </div>
          <span class="chip">{job.status}</span>
        </div>
      {/each}
    {:else}
      <p>学習ジョブがありません。</p>
    {/if}
  </div>
  <div class="mt-4 text-xs text-slate-500">最終更新: {formatDate($jobsQuery.data?.jobs?.[0]?.updated_at)}</div>
</section>
