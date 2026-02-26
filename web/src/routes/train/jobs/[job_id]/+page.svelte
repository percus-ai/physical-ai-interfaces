<script lang="ts">
  import { onDestroy } from 'svelte';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import {
    api,
    type RemoteCheckpointUploadProgressMessage,
    type RemoteCheckpointUploadResult,
    type TrainingReviveProgressMessage,
    type TrainingReviveResult
  } from '$lib/api/client';
  import { getBackendUrl } from '$lib/config';
  import { formatDate } from '$lib/format';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  type JobInfo = {
    job_id?: string;
    job_name?: string;
    status?: string;
    dataset_id?: string;
    profile_instance_id?: string;
    profile_name?: string;
    policy_type?: string;
    ip?: string;
    ssh_user?: string;
    ssh_private_key?: string;
    gpu_model?: string;
    gpus_per_instance?: number;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
  };

  type TrainingConfig = {
    dataset?: { id?: string; video_backend?: string };
    policy?: { type?: string; pretrained_path?: string };
    training?: {
      steps?: number;
      batch_size?: number;
      save_freq?: number;
      log_freq?: number;
    };
    validation?: { enable?: boolean };
    early_stopping?: { enable?: boolean };
  };

  type JobDetailResponse = {
    job?: JobInfo;
    training_config?: TrainingConfig;
    summary?: Record<string, unknown> | null;
  };

  const jobId = $derived(page.params.job_id ?? '');

  const jobQuery = createQuery<JobDetailResponse>(
    toStore(() => ({
      queryKey: ['training', 'job', jobId],
      queryFn: () => api.training.job(jobId) as Promise<JobDetailResponse>,
      enabled: Boolean(jobId)
    }))
  );

  let logsType: 'training' | 'setup' = $state('training');
  let logLines = $state(30);
  let logs = $state('');
  let logsSource = $state('');
  let logsLoading = $state(false);
  let logsError = $state('');

  let metrics: { train?: Array<{ step?: number; loss?: number; ts?: string }>; val?: Array<{ step?: number; loss?: number; ts?: string }> } | null =
    $state(null);
  let metricsLoading = $state(false);
  let metricsError = $state('');

  let copied = $state(false);
  type TrainingJobStreamPayload = {
    job_detail?: JobDetailResponse;
    metrics?: { train?: MetricPoint[]; val?: MetricPoint[] };
  };

  let streamStatus = $state('idle');
  let streamError = $state('');
  let streamLines: string[] = $state([]);
  let streamWs = $state.raw<WebSocket | null>(null);
  let reviveInProgress = $state(false);
  let reviveStage = $state('');
  let reviveMessage = $state('');
  let reviveError = $state('');
  let reviveElapsed: number | null = $state(null);
  let reviveTimeout: number | null = $state(null);
  let reviveEvents: string[] = $state([]);
  let reviveResult: TrainingReviveResult | null = $state(null);
  let reviveCopied = $state(false);
  let remoteCheckpointRoot = $state('');
  let remoteCheckpointNames: string[] = $state([]);
  let selectedRemoteCheckpoint = $state('');
  let remoteCheckpointLoading = $state(false);
  let remoteCheckpointError = $state('');
  let checkpointUploadInProgress = $state(false);
  let checkpointUploadStage = $state('');
  let checkpointUploadMessage = $state('');
  let checkpointUploadError = $state('');
  let checkpointUploadEvents: string[] = $state([]);
  let checkpointUploadResult: RemoteCheckpointUploadResult | null = $state(null);

  type MetricPoint = { step?: number; loss?: number; ts?: string };

  const jobInfo = $derived($jobQuery.data?.job);
  const trainingConfig = $derived($jobQuery.data?.training_config ?? {});
  const summary = $derived($jobQuery.data?.summary ?? {});
  const status = $derived(jobInfo?.status ?? '');
  const datasetId = $derived(trainingConfig?.dataset?.id ?? '');
  const profileId = $derived(jobInfo?.profile_name ?? jobInfo?.profile_instance_id ?? '');
  const trainSeries = $derived(
    (metrics?.train ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? []
  );
  const valSeries = $derived(
    (metrics?.val ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? []
  );

  const isRunning = $derived(['running', 'starting', 'deploying'].includes(status));
  const canDelete = $derived(['completed', 'failed', 'stopped', 'terminated'].includes(status));
  const canRevive = $derived(['completed', 'failed', 'stopped', 'terminated'].includes(status));

  const sshCommand = $derived(
    jobInfo?.ip
      ? `ssh -i ${jobInfo?.ssh_private_key ?? '~/.ssh/id_rsa'} ${jobInfo?.ssh_user ?? 'root'}@${jobInfo.ip}`
      : ''
  );
  const reviveSshCommand = $derived(
    reviveResult?.ip
      ? `ssh -i ${reviveResult?.ssh_private_key ?? '~/.ssh/id_rsa'} ${reviveResult?.ssh_user ?? 'root'}@${reviveResult.ip}`
      : ''
  );

  const wsUrl = (path: string) => getBackendUrl().replace(/^http/, 'ws') + path;

  const refresh = async () => {
    const refetch = $jobQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const stopJob = async () => {
    if (!jobId || !isRunning) return;
    if (!confirm('このジョブを停止しますか?')) return;
    await api.training.stopJob(jobId);
    await refresh();
  };

  const deleteJob = async () => {
    if (!jobId || !canDelete) return;
    if (!confirm('このジョブを削除しますか？（リモートインスタンスも終了します）')) return;
    await api.training.deleteJob(jobId);
    await goto('/train');
  };

  const reviveJob = async () => {
    if (!jobId || !canRevive || reviveInProgress) return;
    if (!confirm('このジョブのインスタンスをCPUで蘇生しますか？')) return;

    reviveInProgress = true;
    reviveStage = '';
    reviveMessage = '';
    reviveError = '';
    reviveElapsed = null;
    reviveTimeout = null;
    reviveEvents = [];
    reviveResult = null;
    reviveCopied = false;

    try {
      const result = await api.training.reviveJobWs(
        jobId,
        (payload: TrainingReviveProgressMessage) => {
          if (payload.type) reviveStage = payload.type;
          if (payload.message) reviveMessage = payload.message;
          if (payload.error) reviveError = payload.error;
          if (typeof payload.elapsed === 'number') reviveElapsed = payload.elapsed;
          if (typeof payload.timeout === 'number') reviveTimeout = payload.timeout;

          const eventLabel = payload.type ?? 'event';
          const eventMessage = payload.error || payload.message || '';
          const line = eventMessage ? `${eventLabel}: ${eventMessage}` : eventLabel;
          reviveEvents = [...reviveEvents, line].slice(-30);
        }
      );
      reviveResult = result;
      reviveMessage = result.message;
      await refresh();
      await fetchRemoteCheckpoints();
    } catch (error) {
      reviveError = error instanceof Error ? error.message : 'インスタンス蘇生に失敗しました。';
    } finally {
      reviveInProgress = false;
    }
  };

  const fetchRemoteCheckpoints = async () => {
    if (!jobId) return;
    remoteCheckpointLoading = true;
    remoteCheckpointError = '';
    try {
      const result = await api.training.remoteCheckpoints(jobId);
      remoteCheckpointRoot = result.checkpoint_root || '';
      remoteCheckpointNames = result.checkpoint_names ?? [];
      if (remoteCheckpointNames.length === 0) {
        selectedRemoteCheckpoint = '';
      } else if (!remoteCheckpointNames.includes(selectedRemoteCheckpoint)) {
        selectedRemoteCheckpoint = remoteCheckpointNames[0];
      }
    } catch (error) {
      remoteCheckpointError =
        error instanceof Error ? error.message : 'リモートcheckpoint一覧の取得に失敗しました。';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
    } finally {
      remoteCheckpointLoading = false;
    }
  };

  const uploadSelectedCheckpoint = async () => {
    if (!jobId || !selectedRemoteCheckpoint || checkpointUploadInProgress) return;
    if (!confirm(`checkpoint ${selectedRemoteCheckpoint} をR2へ登録しますか？`)) return;

    checkpointUploadInProgress = true;
    checkpointUploadStage = '';
    checkpointUploadMessage = '';
    checkpointUploadError = '';
    checkpointUploadEvents = [];
    checkpointUploadResult = null;

    try {
      const result = await api.training.uploadCheckpointWs(
        jobId,
        selectedRemoteCheckpoint,
        (payload: RemoteCheckpointUploadProgressMessage) => {
          if (payload.type) checkpointUploadStage = payload.type;
          if (payload.message) checkpointUploadMessage = payload.message;
          if (payload.error) checkpointUploadError = payload.error;
          const eventType = payload.type ?? 'event';
          const eventMessage = payload.error || payload.message || '';
          const line = eventMessage ? `${eventType}: ${eventMessage}` : eventType;
          checkpointUploadEvents = [...checkpointUploadEvents, line].slice(-30);
        }
      );
      checkpointUploadResult = result;
      checkpointUploadMessage = result.message;
    } catch (error) {
      checkpointUploadError =
        error instanceof Error ? error.message : 'チェックポイントのR2登録に失敗しました。';
    } finally {
      checkpointUploadInProgress = false;
    }
  };

  const fetchLogs = async () => {
    logsError = '';
    if (!jobId) {
      logsError = 'ジョブIDが取得できません。';
      return;
    }
    logsLoading = true;
    try {
      const result = await api.training.logs(jobId, logsType, logLines);
      logs = (result as { logs?: string }).logs ?? '';
      logsSource = (result as { source?: string }).source ?? '';
    } catch (error) {
      logsError = error instanceof Error ? error.message : 'ログ取得に失敗しました。';
    } finally {
      logsLoading = false;
    }
  };

  const fetchMetrics = async () => {
    metricsError = '';
    if (!jobId) {
      metricsError = 'ジョブIDが取得できません。';
      return;
    }
    metricsLoading = true;
    try {
      const result = await api.training.metrics(jobId, 2000);
      metrics = result as typeof metrics;
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'メトリクス取得に失敗しました。';
    } finally {
      metricsLoading = false;
    }
  };

  const copySshCommand = async () => {
    if (!sshCommand) return;
    try {
      await navigator.clipboard.writeText(sshCommand);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      copied = false;
    }
  };

  const copyReviveSshCommand = async () => {
    if (!reviveSshCommand) return;
    try {
      await navigator.clipboard.writeText(reviveSshCommand);
      reviveCopied = true;
      setTimeout(() => (reviveCopied = false), 1500);
    } catch {
      reviveCopied = false;
    }
  };

  const downloadLogs = async () => {
    logsError = '';
    if (!jobId) {
      logsError = 'ジョブIDが取得できません。';
      return;
    }
    try {
      const content = await api.training.downloadLogs(jobId, logsType);
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${jobId}_${logsType}.log`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      logsError = error instanceof Error ? error.message : 'ログのダウンロードに失敗しました。';
    }
  };

  const startLogStream = () => {
    if (!jobId || streamWs) return;
    streamError = '';
    streamLines = [];
    streamStatus = 'connecting';
    const ws = new WebSocket(wsUrl(`/api/training/ws/jobs/${jobId}/logs?log_type=${logsType}`));
    streamWs = ws;

    ws.onopen = () => {
      streamStatus = 'connected';
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data as string) as { type?: string; line?: string; status?: string; message?: string; error?: string };
      if (data.type === 'heartbeat') return;
      if (data.type === 'log' && data.line) {
        streamLines = [...streamLines, data.line].slice(-200);
      } else if (data.type === 'status') {
        streamStatus = data.status || 'status';
        if (data.status && data.status !== 'connected') {
          ws.close();
        }
      } else if (data.type === 'error') {
        streamError = data.error || 'ログストリーミングに失敗しました。';
        streamStatus = 'error';
        ws.close();
      }
    };

    ws.onerror = () => {
      streamError = 'WebSocket接続に失敗しました。';
      streamStatus = 'error';
    };

    ws.onclose = () => {
      streamWs = null;
      if (streamStatus === 'connected') {
        streamStatus = 'closed';
      }
    };
  };

  const stopLogStream = () => {
    streamWs?.close();
    streamWs = null;
    streamStatus = 'stopped';
  };

  $effect(() => {
    if (!isRunning && streamWs) {
      stopLogStream();
    }
  });

  let lastJobId = '';
  $effect(() => {
    if (jobId && jobId !== lastJobId) {
      lastJobId = jobId;
      streamWs?.close();
      streamWs = null;
      streamLines = [];
      streamStatus = 'idle';
      streamError = '';
      logs = '';
      logsSource = '';
      logsError = '';
      metrics = null;
      metricsError = '';
      reviveInProgress = false;
      reviveStage = '';
      reviveMessage = '';
      reviveError = '';
      reviveElapsed = null;
      reviveTimeout = null;
      reviveEvents = [];
      reviveResult = null;
      reviveCopied = false;
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointLoading = false;
      remoteCheckpointError = '';
      checkpointUploadInProgress = false;
      checkpointUploadStage = '';
      checkpointUploadMessage = '';
      checkpointUploadError = '';
      checkpointUploadEvents = [];
      checkpointUploadResult = null;
    }
  });

  let stopTrainingStream = () => {};
  let lastStreamJobId = '';

  $effect(() => {
    if (jobId && jobId !== lastStreamJobId) {
      stopTrainingStream();
      lastStreamJobId = jobId;
      stopTrainingStream = connectStream<TrainingJobStreamPayload>({
        path: `/api/stream/training/jobs/${encodeURIComponent(jobId)}`,
        onMessage: (payload) => {
          if (payload.job_detail) {
            queryClient.setQueryData(['training', 'job', jobId], payload.job_detail);
          }
          if (payload.metrics) {
            metrics = payload.metrics;
            metricsLoading = false;
            metricsError = '';
          }
        }
      });
    }
  });

  onDestroy(() => {
    stopTrainingStream();
    streamWs?.close();
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">学習ジョブ詳細</h1>
      <p class="mt-2 text-sm text-slate-600">
        {jobInfo?.job_name ?? 'ジョブ名取得中...'}
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">{status || 'unknown'}</span>
        {#if jobInfo?.gpu_model}
          <span class="chip">{jobInfo.gpu_model} x {jobInfo.gpus_per_instance ?? 1}</span>
        {/if}
        {#if jobInfo?.dataset_id}
          <span class="chip">{jobInfo.dataset_id}</span>
        {/if}
      </div>
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" href="/train">一覧へ戻る</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={refresh}>更新</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
  <div class="space-y-6 min-w-0">
    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">ジョブID</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.job_id ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.policy_type ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">作成日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.created_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">開始日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.started_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">完了日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.completed_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">IP</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.ip ?? '-'}</p>
        </div>
      </div>
    </section>

    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">loss推移</h2>
        <Button.Root class="btn-ghost" type="button" onclick={fetchMetrics} disabled={metricsLoading}>
          {metricsLoading ? '取得中...' : '更新'}
        </Button.Root>
      </div>
      {#if metricsError}
        <p class="mt-3 text-sm text-rose-600">{metricsError}</p>
      {:else if metrics}
        {#if trainSeries.length || valSeries.length}
          <div class="mt-4 space-y-4 text-sm text-slate-600">
            <div class="flex flex-wrap items-center gap-4 text-xs text-slate-500">
              <span class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-brand"></span>
                Train loss
              </span>
              <span class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-orange-400"></span>
                Val loss
              </span>
            </div>
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <Plot height={240} grid>
                <GridY />
                <AxisX tickCount={6} />
                <AxisY tickCount={6} />
                {#if trainSeries.length}
                  <Line data={trainSeries} x="step" y="loss" stroke="#5b7cfa" strokeWidth={2} />
                {/if}
                {#if valSeries.length}
                  <Line data={valSeries} x="step" y="loss" stroke="#fb923c" strokeWidth={2} />
                {/if}
              </Plot>
            </div>
          </div>
        {:else}
          <p class="mt-3 text-sm text-slate-500">まだデータがありません。</p>
        {/if}
      {:else}
        <p class="mt-3 text-sm text-slate-500">まだデータがありません。</p>
      {/if}
    </section>

    <section class="card p-6">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-xl font-semibold text-slate-900">ログ内容</h2>
        <span class="text-xs text-slate-500">表示: {logsType === 'training' ? '学習ログ' : 'セットアップログ'}</span>
      </div>
      <div class="mt-4 space-y-4 text-sm text-slate-600">
        {#if logsError}
          <p class="text-sm text-rose-600">{logsError}</p>
        {/if}
        {#if streamError}
          <p class="text-sm text-rose-600">{streamError}</p>
        {/if}
        {#if isRunning}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
            <p class="label">ログ {logsSource === 'r2' ? '(R2)' : ''}</p>
            {#if logs}
              <pre class="mt-2 whitespace-pre-wrap text-xs text-slate-700">{logs}</pre>
            {:else}
              <p class="mt-2 text-xs text-slate-500">ログは未取得です。</p>
            {/if}
          </div>
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
            <p class="label">ストリーミングログ</p>
            {#if streamLines.length}
              <pre class="mt-2 whitespace-pre-wrap text-xs text-slate-700">{streamLines.join('\n')}</pre>
            {:else}
              <p class="mt-2 text-xs text-slate-500">ストリーミングは停止中です。</p>
            {/if}
          </div>
        {:else}
          <p class="text-sm text-slate-500">実行中ではないため、ログはダウンロードのみ対応しています。</p>
        {/if}
      </div>
    </section>

    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">設定</h2>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2 text-sm text-slate-600">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">データセット</p>
          <div class="mt-2 space-y-2 text-sm text-slate-600">
            <div>
              <p class="text-xs text-slate-500">データセットID</p>
              <p class="font-semibold text-slate-800 break-words">
                {datasetId || '-'}
              </p>
            </div>
            <div>
              <p class="text-xs text-slate-500">プロフィール</p>
              <p class="font-semibold text-slate-800 break-words">
                {profileId || '-'}
              </p>
            </div>
          </div>
          <p class="mt-2 text-xs text-slate-500">
            video_backend: {trainingConfig?.dataset?.video_backend ?? 'auto'}
          </p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{trainingConfig?.policy?.type ?? '-'}</p>
          <p class="mt-1 text-xs text-slate-500">pretrained: {trainingConfig?.policy?.pretrained_path ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">学習</p>
          <p class="mt-2 font-semibold text-slate-800">
            steps: {trainingConfig?.training?.steps ?? '-'} / batch: {trainingConfig?.training?.batch_size ?? '-'}
          </p>
          <p class="mt-1 text-xs text-slate-500">
            save_freq: {trainingConfig?.training?.save_freq ?? '-'} / log_freq: {trainingConfig?.training?.log_freq ?? '-'}
          </p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">検証 / Early</p>
          <p class="mt-2 font-semibold text-slate-800">
            validation: {trainingConfig?.validation?.enable ? '有効' : '無効'}
          </p>
          <p class="mt-1 text-xs text-slate-500">
            early_stopping: {trainingConfig?.early_stopping?.enable ? '有効' : '無効'}
          </p>
        </div>
      </div>
      {#if Object.keys(summary).length}
        <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">Summary</p>
          <div class="mt-2 grid gap-2">
            {#each Object.entries(summary) as [key, value]}
              <p class="text-xs text-slate-500">{key}: <span class="text-slate-800">{value}</span></p>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  </div>

  <div class="space-y-6 min-w-0">
    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">操作</h2>
      <div class="mt-4 grid gap-3">
        <Button.Root class="btn-primary" type="button" onclick={stopJob} disabled={!isRunning}>
          {isRunning ? 'ジョブを停止' : '停止不可'}
        </Button.Root>
        {#if canRevive}
          <Button.Root class="btn-ghost" type="button" onclick={reviveJob} disabled={reviveInProgress}>
            {reviveInProgress ? 'インスタンス蘇生中...' : 'インスタンスを蘇生'}
          </Button.Root>
        {/if}
      </div>
      <p class="mt-3 text-xs text-slate-500">
        停止・蘇生はジョブステータスに応じて有効化されます。
      </p>
      {#if isRunning}
        <div class="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <span class="chip">ストリーミング更新</span>
          <span>進捗とステータスはストリーミングで更新します。</span>
        </div>
      {/if}
    </section>

    {#if canRevive || reviveInProgress || reviveResult || reviveError || reviveEvents.length}
      <section class="card p-6">
        <h2 class="text-xl font-semibold text-slate-900">インスタンス蘇生</h2>
        <p class="mt-2 text-sm text-slate-600">
          終了済みジョブに対して、OSストレージからCPUインスタンスを再作成します。
        </p>
        <div class="mt-4 space-y-3 text-sm text-slate-600">
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
            <p class="label">救済チェックポイント登録</p>
            <p class="mt-2 text-xs text-slate-500">
              リモート上の checkpoint ディレクトリから保存対象を選択して R2 に登録します。
            </p>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button.Root class="btn-ghost" type="button" onclick={fetchRemoteCheckpoints} disabled={remoteCheckpointLoading || checkpointUploadInProgress}>
                {remoteCheckpointLoading ? '候補取得中...' : '候補を取得'}
              </Button.Root>
            </div>
            {#if remoteCheckpointRoot}
              <p class="mt-3 text-xs text-slate-500 break-all">root: {remoteCheckpointRoot}</p>
            {/if}
            {#if remoteCheckpointError}
              <p class="mt-3 text-sm text-rose-600">{remoteCheckpointError}</p>
            {/if}
            {#if remoteCheckpointNames.length}
              <label class="mt-3 block text-sm font-semibold text-slate-700">
                <span class="label">保存するcheckpoint</span>
                <select class="input mt-2" bind:value={selectedRemoteCheckpoint} disabled={checkpointUploadInProgress}>
                  {#each remoteCheckpointNames as checkpointName}
                    <option value={checkpointName}>{checkpointName}</option>
                  {/each}
                </select>
              </label>
              <div class="mt-3 flex flex-wrap gap-2">
                <Button.Root class="btn-primary" type="button" onclick={uploadSelectedCheckpoint} disabled={!selectedRemoteCheckpoint || checkpointUploadInProgress}>
                  {checkpointUploadInProgress ? 'R2登録中...' : '選択したcheckpointをR2登録'}
                </Button.Root>
              </div>
            {:else if !remoteCheckpointLoading}
              <p class="mt-3 text-xs text-slate-500">候補はまだ取得されていません。</p>
            {/if}
          </div>

          {#if reviveStage}
            <span class="chip">フェーズ: {reviveStage}</span>
          {/if}
          {#if reviveElapsed !== null}
            <p class="text-xs text-slate-500">
              経過: {reviveElapsed}s{#if reviveTimeout !== null} / {reviveTimeout}s{/if}
            </p>
          {/if}
          {#if reviveMessage}
            <p class="text-sm text-slate-700">{reviveMessage}</p>
          {/if}
          {#if reviveError}
            <p class="text-sm text-rose-600">{reviveError}</p>
          {/if}
          {#if checkpointUploadStage}
            <span class="chip">登録フェーズ: {checkpointUploadStage}</span>
          {/if}
          {#if checkpointUploadMessage}
            <p class="text-sm text-slate-700">{checkpointUploadMessage}</p>
          {/if}
          {#if checkpointUploadError}
            <p class="text-sm text-rose-600">{checkpointUploadError}</p>
          {/if}
          {#if reviveEvents.length}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">進捗ログ</p>
              <pre class="mt-2 whitespace-pre-wrap text-xs text-slate-700">{reviveEvents.join('\n')}</pre>
            </div>
          {/if}
          {#if checkpointUploadEvents.length}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">checkpoint登録ログ</p>
              <pre class="mt-2 whitespace-pre-wrap text-xs text-slate-700">{checkpointUploadEvents.join('\n')}</pre>
            </div>
          {/if}
          {#if checkpointUploadResult}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">checkpoint登録結果</p>
              <div class="mt-2 space-y-1 text-xs text-slate-600">
                <p>checkpoint: <span class="font-semibold text-slate-800">{checkpointUploadResult.checkpoint_name}</span></p>
                <p>step: <span class="font-semibold text-slate-800">{checkpointUploadResult.step}</span></p>
                <p>R2 path: <span class="font-semibold text-slate-800 break-all">{checkpointUploadResult.r2_step_path}</span></p>
                <p>model_id: <span class="font-semibold text-slate-800 break-all">{checkpointUploadResult.model_id}</span></p>
                <p>
                  DB登録:
                  <span class="font-semibold text-slate-800">
                    {checkpointUploadResult.db_registered ? '完了' : '未完了'}
                  </span>
                </p>
              </div>
            </div>
          {/if}
          {#if reviveResult}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">蘇生結果</p>
              <div class="mt-2 space-y-1 text-xs text-slate-600">
                <p>旧インスタンスID: <span class="font-semibold text-slate-800 break-all">{reviveResult.old_instance_id}</span></p>
                <p>新インスタンスID: <span class="font-semibold text-slate-800 break-all">{reviveResult.instance_id}</span></p>
                <p>ストレージID: <span class="font-semibold text-slate-800 break-all">{reviveResult.volume_id}</span></p>
                <p>インスタンスタイプ: <span class="font-semibold text-slate-800">{reviveResult.instance_type}</span></p>
                <p>ロケーション: <span class="font-semibold text-slate-800">{reviveResult.location}</span></p>
                <p>IP: <span class="font-semibold text-slate-800">{reviveResult.ip}</span></p>
                <p>SSHユーザー: <span class="font-semibold text-slate-800">{reviveResult.ssh_user}</span></p>
                <p>SSH鍵: <span class="font-semibold text-slate-800 break-all">{reviveResult.ssh_private_key}</span></p>
              </div>
              <div class="mt-3 rounded-xl border border-slate-200/60 bg-slate-50/80 p-3 text-xs text-slate-600">
                <p class="label">SSHコマンド</p>
                <p class="mt-2 font-semibold text-slate-800 break-all">{reviveSshCommand || '-'}</p>
              </div>
              <div class="mt-3 flex flex-wrap gap-2">
                <Button.Root class="btn-ghost" type="button" onclick={copyReviveSshCommand} disabled={!reviveSshCommand}>
                  SSHコマンドをコピー
                </Button.Root>
                {#if reviveCopied}
                  <span class="chip">コピーしました</span>
                {/if}
              </div>
            </div>
          {/if}
        </div>
      </section>
    {/if}

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ログ</h2>
      <div class="mt-4 grid gap-3 text-sm text-slate-600">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ログ種別</span>
          <select class="input mt-2" bind:value={logsType} disabled={Boolean(streamWs)}>
            <option value="training">学習ログ</option>
            <option value="setup">セットアップログ</option>
          </select>
        </label>
        {#if isRunning}
          <Button.Root class="btn-ghost" type="button" onclick={downloadLogs}>
            ログをダウンロード
          </Button.Root>
          <label class="text-sm font-semibold text-slate-700">
            <span class="label">取得行数</span>
            <input class="input mt-2" type="number" min="1" bind:value={logLines} />
          </label>
          <Button.Root class="btn-ghost" type="button" onclick={fetchLogs} disabled={logsLoading}>
            {logsLoading ? '取得中...' : 'ログを取得'}
          </Button.Root>
          <div class="flex flex-wrap gap-2">
            <Button.Root class="btn-primary" type="button" onclick={startLogStream} disabled={Boolean(streamWs)}>
              ストリーミング開始
            </Button.Root>
            <Button.Root class="btn-ghost" type="button" onclick={stopLogStream} disabled={!streamWs}>
              ストリーミング停止
            </Button.Root>
            <span class="chip">状態: {streamStatus}</span>
          </div>
        {:else}
          <Button.Root class="btn-primary" type="button" onclick={downloadLogs}>
            ログをダウンロード
          </Button.Root>
        {/if}
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">SSH接続</h2>
      <p class="mt-2 text-sm text-slate-600">ジョブ詳細のIP情報を使って接続します。</p>
      <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
        <p class="label">コマンド</p>
        <p class="mt-2 font-semibold text-slate-800">{sshCommand || 'IPが取得できていません'}</p>
      </div>
      <div class="mt-4 flex flex-wrap gap-3">
        <Button.Root class="btn-ghost" type="button" onclick={copySshCommand} disabled={!sshCommand}>
          コピー
        </Button.Root>
        {#if copied}
          <span class="chip">コピーしました</span>
        {/if}
      </div>
    </section>
  </div>
</section>
