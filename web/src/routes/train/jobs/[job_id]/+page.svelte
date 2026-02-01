<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import { api } from '$lib/api/client';
  import { getBackendUrl } from '$lib/config';
  import { formatDate } from '$lib/format';

  type JobInfo = {
    job_id?: string;
    job_name?: string;
    status?: string;
    dataset_id?: string;
    profile_instance_id?: string;
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

  let jobId = '';
  $: jobId = $page.params.job_id;

  const jobQuery = createQuery<JobDetailResponse>(
    derived(page, ($page) => {
      const currentId = $page.params.job_id;
      return {
        queryKey: ['training', 'job', currentId],
        queryFn: () => api.training.job(currentId) as Promise<JobDetailResponse>,
        enabled: Boolean(currentId)
      };
    })
  );

  let logsType: 'training' | 'setup' = 'training';
  let logLines = 30;
  let logs = '';
  let logsSource = '';
  let logsLoading = false;
  let logsError = '';

  let metrics: { train?: Array<{ step?: number; loss?: number; ts?: string }>; val?: Array<{ step?: number; loss?: number; ts?: string }> } | null =
    null;
  let metricsLoading = false;
  let metricsError = '';

  let copied = false;
  let autoRefresh = true;
  let refreshTimer: ReturnType<typeof setInterval> | null = null;
  let refreshTick = 0;

  let streamStatus = 'idle';
  let streamError = '';
  let streamLines: string[] = [];
  let streamWs: WebSocket | null = null;

  type MetricPoint = { step?: number; loss?: number; ts?: string };

  $: jobInfo = $jobQuery.data?.job;
  $: trainingConfig = $jobQuery.data?.training_config ?? {};
  $: summary = $jobQuery.data?.summary ?? {};
  $: status = jobInfo?.status ?? '';
  $: datasetId = trainingConfig?.dataset?.id ?? '';
  $: profileId = jobInfo?.profile_instance_id ?? '';
  $: trainSeries =
    (metrics?.train ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? [];
  $: valSeries =
    (metrics?.val ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? [];

  $: isRunning = ['running', 'starting', 'deploying'].includes(status);
  $: canDelete = ['completed', 'failed', 'stopped', 'terminated'].includes(status);

  $: sshCommand = jobInfo?.ip
    ? `ssh -i ${jobInfo?.ssh_private_key ?? '~/.ssh/id_rsa'} ${jobInfo?.ssh_user ?? 'root'}@${jobInfo.ip}`
    : '';

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

  const startAutoRefresh = () => {
    if (refreshTimer || !autoRefresh) return;
    refreshTimer = setInterval(() => {
      if (!autoRefresh || !isRunning) return;
      $jobQuery?.refetch?.();
      refreshTick += 1;
      if (refreshTick % 3 === 0) {
        fetchMetrics();
      }
    }, 5000);
  };

  const stopAutoRefresh = () => {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = null;
  };

  $: if (!isRunning && streamWs) {
    stopLogStream();
  }

  $: if (autoRefresh && isRunning) {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }

  let lastJobId = '';
  $: if (jobId && jobId !== lastJobId) {
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
  }

  onMount(() => {
    fetchMetrics();
    if (isRunning) {
      startAutoRefresh();
    }
  });

  onDestroy(() => {
    stopAutoRefresh();
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
      </div>
      <p class="mt-3 text-xs text-slate-500">
        停止・削除は実行中ステータスに応じて有効化されます。
      </p>
      {#if isRunning}
        <div class="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <span class="chip">自動更新中</span>
          <span>5秒間隔で進捗とステータスを更新します。</span>
        </div>
      {/if}
    </section>

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
