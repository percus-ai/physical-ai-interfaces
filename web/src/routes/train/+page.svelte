<script lang="ts">
  import { Button, Tabs } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import GpuAvailabilityBoard from '$lib/components/training/GpuAvailabilityBoard.svelte';
  import { formatDate } from '$lib/format';
  import { GPU_MODELS } from '$lib/policies';
  import type { GpuAvailabilityResponse } from '$lib/types/training';

  type TrainingJob = {
    job_id: string;
    job_name?: string;
    dataset_id?: string;
    policy_type?: string;
    status?: string;
    updated_at?: string;
  };

  type JobListResponse = {
    jobs?: TrainingJob[];
    total?: number;
  };

  const jobsQuery = createQuery<JobListResponse>({
    queryKey: ['training', 'jobs'],
    queryFn: api.training.jobs
  });

  const gpuAvailabilityQuery = createQuery<GpuAvailabilityResponse>({
    queryKey: ['training', 'gpu-availability'],
    queryFn: api.training.gpuAvailability
  });

  const gpuModelOrder = $derived(GPU_MODELS.map((gpu) => gpu.name));
  let activeTab = $state<'availability' | 'jobs'>('jobs');
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル学習</h1>
      <p class="mt-2 text-sm text-slate-600">
        利用可能なポリシー一覧と、学習ジョブの状態を確認します。
      </p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary" href="/train/new">新規学習</Button.Root>
      <Button.Root class="btn-ghost opacity-50 cursor-not-allowed" disabled title="準備中">
        継続学習
      </Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <Tabs.Root bind:value={activeTab}>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
        <Tabs.Trigger
          value="jobs"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          学習ジョブ一覧
        </Tabs.Trigger>
        <Tabs.Trigger
          value="availability"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          GPU空き状況
        </Tabs.Trigger>
      </Tabs.List>

      {#if activeTab === 'jobs'}
        <Button.Root class="btn-ghost" type="button" onclick={() => $jobsQuery?.refetch?.()}>更新</Button.Root>
      {/if}
    </div>

    <Tabs.Content value="availability" class="mt-4">
      <h2 class="text-xl font-semibold text-slate-900">GPU 空き状況 (Verda)</h2>
      <p class="mt-1 text-sm text-slate-500">モデルごとに展開して可否・価格・拠点数を確認できます。</p>
      <div class="mt-4">
        <GpuAvailabilityBoard
          items={$gpuAvailabilityQuery.data?.available ?? []}
          loading={$gpuAvailabilityQuery.isLoading}
          showOnlyAvailableDefault={true}
          preferredModelOrder={gpuModelOrder}
        />
      </div>
    </Tabs.Content>

    <Tabs.Content value="jobs" class="mt-4">
      <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
      <div class="mt-4 space-y-3 text-sm text-slate-600">
        {#if $jobsQuery.isLoading}
          <p>読み込み中...</p>
        {:else if $jobsQuery.data?.jobs?.length}
          {#each $jobsQuery.data.jobs as job}
            <a
              class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3 transition hover:border-brand/40 hover:bg-white"
              href={`/train/jobs/${job.job_id}`}
            >
              <div>
                <p class="font-semibold text-slate-800">{job.job_name}</p>
                <p class="text-xs text-slate-500">{job.dataset_id ?? '-'} / {job.policy_type ?? '-'}</p>
              </div>
              <span class="chip">{job.status}</span>
            </a>
          {/each}
        {:else}
          <p>学習ジョブがありません。</p>
        {/if}
      </div>
      <div class="mt-4 text-xs text-slate-500">最終更新: {formatDate($jobsQuery.data?.jobs?.[0]?.updated_at)}</div>
    </Tabs.Content>
  </Tabs.Root>
</section>
