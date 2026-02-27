<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api, type ModelSyncJobState, type ModelSyncJobStatus } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';
  import { connectStream } from '$lib/realtime/stream';

  type ModelSummary = {
    id: string;
    name?: string;
    profile_name?: string;
    policy_type?: string;
    dataset_id?: string;
    size_bytes?: number;
    is_local?: boolean;
    status?: string;
    created_at?: string;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  type DatasetSummary = {
    id: string;
    name?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: ['storage', 'models', 'manage'],
    queryFn: () => api.storage.models()
  });

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['storage', 'datasets', 'lookup'],
    queryFn: () => api.storage.datasets()
  });

  const models = $derived($modelsQuery.data?.models ?? []);
  const datasetMap = $derived(
    new Map(
      ($datasetsQuery.data?.datasets ?? []).map((dataset) => [
        dataset.id,
        dataset.name ?? dataset.id
      ])
    )
  );

  const displayModelLabel = (model: ModelSummary) => model.name ?? model.id;
  const isActiveJobState = (state?: ModelSyncJobState) => state === 'queued' || state === 'running';
  const isTerminalJobState = (state?: ModelSyncJobState) =>
    state === 'completed' || state === 'failed' || state === 'cancelled';

  let syncAllPending = $state(false);
  let syncMessage = $state('');
  let syncError = $state('');
  let jobsById = $state<Record<string, ModelSyncJobStatus>>({});
  let activeJobsByModelId = $state<Record<string, ModelSyncJobStatus>>({});
  const streamStops = new Map<string, () => void>();

  const anyActiveSync = $derived(Object.keys(activeJobsByModelId).length > 0);
  const syncPending = $derived(syncAllPending || anyActiveSync);

  const activeJobOf = (modelId: string) => activeJobsByModelId[modelId] ?? null;

  const normalizeJob = (job: ModelSyncJobStatus): ModelSyncJobStatus => {
    const progress = Number(job.progress_percent ?? 0);
    const normalizedProgress = Number.isFinite(progress) ? Math.min(100, Math.max(0, progress)) : 0;
    return {
      ...job,
      progress_percent: normalizedProgress,
      detail: {
        files_done: Number(job.detail?.files_done ?? 0),
        total_files: Number(job.detail?.total_files ?? 0),
        transferred_bytes: Number(job.detail?.transferred_bytes ?? 0),
        total_bytes: Number(job.detail?.total_bytes ?? 0),
        current_file: job.detail?.current_file ?? null
      }
    };
  };

  const isNewerJobSnapshot = (next: ModelSyncJobStatus, prev: ModelSyncJobStatus | undefined) => {
    if (!prev) return true;
    const nextTs = Date.parse(next.updated_at ?? '');
    const prevTs = Date.parse(prev.updated_at ?? '');
    if (Number.isNaN(nextTs) || Number.isNaN(prevTs)) return true;
    return nextTs >= prevTs;
  };

  const stopJobStream = (jobId: string) => {
    const stop = streamStops.get(jobId);
    if (!stop) return;
    stop();
    streamStops.delete(jobId);
  };

  const applyJobSnapshot = (job: ModelSyncJobStatus) => {
    const normalized = normalizeJob(job);
    const previous = jobsById[normalized.job_id];
    if (!isNewerJobSnapshot(normalized, previous)) return;

    jobsById = {
      ...jobsById,
      [normalized.job_id]: normalized
    };

    if (isActiveJobState(normalized.state)) {
      activeJobsByModelId = {
        ...activeJobsByModelId,
        [normalized.model_id]: normalized
      };
      return;
    }

    const activeJob = activeJobsByModelId[normalized.model_id];
    if (activeJob?.job_id === normalized.job_id) {
      const next = { ...activeJobsByModelId };
      delete next[normalized.model_id];
      activeJobsByModelId = next;
    }
    if (isTerminalJobState(normalized.state)) {
      stopJobStream(normalized.job_id);
      void refetchModels();
    }
  };

  const ensureJobStream = (jobId: string) => {
    if (!jobId || streamStops.has(jobId)) return;

    let stop = () => {};
    stop = connectStream<ModelSyncJobStatus>({
      path: `/api/stream/storage/model-sync/jobs/${encodeURIComponent(jobId)}`,
      onMessage: (payload) => {
        applyJobSnapshot(payload);
      },
      onError: () => {
        // Fallback polling in action handlers keeps status eventually consistent.
      }
    });

    streamStops.set(jobId, () => {
      stop();
    });
  };

  const refetchModels = async () => {
    await $modelsQuery?.refetch?.();
  };

  const loadActiveJobs = async () => {
    const response = await api.storage.modelSyncJobs(false);
    const activeJobs = (response.jobs ?? []).map(normalizeJob);

    const nextJobsById = { ...jobsById };
    const nextActive: Record<string, ModelSyncJobStatus> = {};
    const activeJobIds = new Set<string>();

    for (const job of activeJobs) {
      nextJobsById[job.job_id] = job;
      nextActive[job.model_id] = job;
      activeJobIds.add(job.job_id);
      ensureJobStream(job.job_id);
    }

    jobsById = nextJobsById;
    activeJobsByModelId = nextActive;

    for (const [jobId] of streamStops) {
      if (!activeJobIds.has(jobId)) {
        stopJobStream(jobId);
      }
    }
  };

  const startModelSync = async (modelId: string) => {
    const accepted = await api.storage.syncModel(modelId);
    const snapshot = await api.storage.modelSyncJob(accepted.job_id);
    applyJobSnapshot(snapshot);
    ensureJobStream(accepted.job_id);
    return snapshot;
  };

  const cancelModelSync = async (jobId: string) => {
    await api.storage.cancelModelSyncJob(jobId);
    const snapshot = await api.storage.modelSyncJob(jobId);
    applyJobSnapshot(snapshot);
    ensureJobStream(jobId);
    return snapshot;
  };

  const waitForTerminalJob = async (jobId: string) => {
    while (true) {
      const snapshot = await api.storage.modelSyncJob(jobId);
      applyJobSnapshot(snapshot);
      if (isTerminalJobState(snapshot.state)) {
        return snapshot;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  };

  const handleSyncModel = async (model: ModelSummary) => {
    const modelId = model.id;
    if (!modelId) return;
    const activeJob = activeJobOf(modelId);

    syncMessage = '';
    syncError = '';

    if (activeJob) {
      try {
        const snapshot = await cancelModelSync(activeJob.job_id);
        syncMessage = snapshot.message ?? `${modelId} の中断を要求しました。`;
      } catch (err) {
        syncError = err instanceof Error ? err.message : 'モデル同期の中断に失敗しました。';
      }
      return;
    }

    if (model.is_local || syncAllPending || anyActiveSync) return;

    try {
      const started = await startModelSync(modelId);
      syncMessage = started.message ?? `${modelId} の同期を開始しました。`;
    } catch (err) {
      syncError = err instanceof Error ? err.message : 'モデル同期の開始に失敗しました。';
    }
  };

  const handleSyncAll = async () => {
    if (syncPending) return;

    const targets = models.filter((model) => !model.is_local);
    if (!targets.length) {
      syncMessage = '未同期モデルはありません。';
      syncError = '';
      return;
    }

    syncAllPending = true;
    syncMessage = '';
    syncError = '';

    let completed = 0;
    let cancelled = 0;
    let failed = 0;
    const failedIds: string[] = [];

    try {
      for (const model of targets) {
        const started = await startModelSync(model.id);
        const finished = await waitForTerminalJob(started.job_id);
        if (finished.state === 'completed') {
          completed += 1;
          continue;
        }
        if (finished.state === 'cancelled') {
          cancelled += 1;
          continue;
        }
        failed += 1;
        failedIds.push(model.id);
      }

      const summary = [`成功 ${completed}`, `中断 ${cancelled}`, `失敗 ${failed}`].join(' / ');
      syncMessage = `全モデル同期完了: ${summary}`;
      if (failedIds.length) {
        const preview = failedIds.slice(0, 5).join(', ');
        const suffix = failedIds.length > 5 ? ' ...' : '';
        syncError = `失敗モデル: ${preview}${suffix}`;
      }
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      syncError = err instanceof Error ? err.message : '全モデル同期に失敗しました。';
    } finally {
      syncAllPending = false;
    }
  };

  const handleRefresh = async () => {
    syncError = '';
    await refetchModels();
    await loadActiveJobs();
  };

  const syncButtonLabel = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return '中断';
    if (model.is_local) return '同期済';
    return '同期';
  };

  const isSyncButtonDisabled = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return false;
    if (model.is_local) return true;
    if (syncAllPending) return true;
    if (anyActiveSync) return true;
    return false;
  };

  $effect(() => {
    let disposed = false;

    const initialize = async () => {
      try {
        await loadActiveJobs();
      } catch (err) {
        if (disposed) return;
        syncError = err instanceof Error ? err.message : '同期ジョブ状態の取得に失敗しました。';
      }
    };

    void initialize();

    return () => {
      disposed = true;
      for (const stop of streamStops.values()) {
        stop();
      }
      streamStops.clear();
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなモデルを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">ビューに戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || !models.length}>
        {syncAllPending ? '全て同期中...' : '全て同期'}
      </button>
      <button class="btn-ghost" type="button" onclick={handleRefresh} disabled={syncAllPending}>
        更新
      </button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">ID</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">ポリシー</th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">状態</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3">同期</th>
          <th class="pb-3">詳細</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if models.length}
          {#each models as model}
            {@const activeJob = activeJobOf(model.id)}
            {@const progressPercent = Number(activeJob?.progress_percent ?? 0)}
            <tr class="border-t border-slate-200/60">
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={model.id}>
                  {displayModelLabel(model)}
                </span>
              </td>
              <td class="py-3">{model.profile_name ?? '-'}</td>
              <td class="py-3">{model.policy_type ?? '-'}</td>
              <td class="py-3">
                {#if model.dataset_id}
                  <a
                    class="text-brand hover:underline"
                    href={`/storage/datasets/${model.dataset_id}`}
                    title={datasetMap.get(model.dataset_id) ?? model.dataset_id}
                  >
                    詳細
                  </a>
                {:else}
                  -
                {/if}
              </td>
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3"><span class="chip">{model.status}</span></td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              <td class="py-3">
                <button
                  class="btn-ghost"
                  type="button"
                  onclick={() => handleSyncModel(model)}
                  disabled={isSyncButtonDisabled(model)}
                >
                  {syncButtonLabel(model)}
                </button>
                {#if activeJob}
                  <div class="mt-2 max-w-[220px]">
                    <div class="h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div
                        class="h-full rounded-full bg-brand transition-all duration-200"
                        style={`width: ${Math.min(100, Math.max(0, progressPercent))}%;`}
                      ></div>
                    </div>
                    <p class="mt-1 text-xs text-slate-500">
                      {Math.round(progressPercent)}% {activeJob.message ?? '同期中...'}
                    </p>
                  </div>
                {/if}
              </td>
              <td class="py-3 text-right">
                <Button.Root class="btn-ghost" href={`/storage/models/${model.id}`}>詳細</Button.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">モデルがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  {#if syncMessage}
    <p class="mt-4 text-sm text-emerald-600">{syncMessage}</p>
  {/if}
  {#if syncError}
    <p class="mt-2 text-sm text-rose-600">{syncError}</p>
  {/if}
</section>
