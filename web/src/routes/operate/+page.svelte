<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import {
    api,
    type StartupOperationAcceptedResponse,
    type StartupOperationStatusResponse
  } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import ActiveSessionSection from '$lib/components/ActiveSessionSection.svelte';
  import ActiveSessionCard from '$lib/components/ActiveSessionCard.svelte';
  import TaskCandidateCombobox from '$lib/components/TaskCandidateCombobox.svelte';

  type InferenceModel = {
    model_id?: string;
    name?: string;
    policy_type?: string;
    source?: string;
    size_mb?: number;
    is_loaded?: boolean;
    is_local?: boolean;
    task_candidates?: string[];
  };
  const PI0_POLICY_TYPES = new Set(['pi0', 'pi05']);

  type InferenceModelsResponse = {
    models?: InferenceModel[];
  };

  type InferenceDeviceCompatibilityResponse = {
    devices?: Array<{
      device?: string;
      available?: boolean;
      memory_total_mb?: number | null;
      memory_free_mb?: number | null;
    }>;
    recommended?: string;
  };

  type RunnerStatus = {
    active?: boolean;
    session_id?: string;
    task?: string;
    queue_length?: number;
    last_error?: string;
  };

  type GpuHostStatus = {
    status?: string;
    session_id?: string;
    pid?: number;
    last_error?: string;
  };

  type InferenceRunnerStatusResponse = {
    runner_status?: RunnerStatus;
    gpu_host_status?: GpuHostStatus;
  };

  type OperateStatusResponse = {
    backend?: { status?: string; message?: string };
    vlabor?: { status?: string; message?: string };
    lerobot?: { status?: string; message?: string };
    network?: { status?: string; message?: string; details?: Record<string, any> };
    driver?: { status?: string; message?: string; details?: Record<string, any> };
  };

  type OperateStatusStreamPayload = {
    vlabor_status?: Record<string, any>;
    inference_runner_status?: InferenceRunnerStatusResponse;
    operate_status?: OperateStatusResponse;
  };

  const inferenceModelsQuery = createQuery<InferenceModelsResponse>({
    queryKey: ['inference', 'models'],
    queryFn: api.inference.models
  });

  const inferenceDeviceQuery = createQuery<InferenceDeviceCompatibilityResponse>({
    queryKey: ['inference', 'device-compatibility'],
    queryFn: api.inference.deviceCompatibility
  });

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>({
    queryKey: ['inference', 'runner', 'status'],
    queryFn: api.inference.runnerStatus
  });

  const operateStatusQuery = createQuery<OperateStatusResponse>({
    queryKey: ['operate', 'status'],
    queryFn: api.operate.status
  });

  const resolveModelId = (model: InferenceModel) => model.model_id ?? model.name ?? '';

  const renderGpuStatus = (status?: string) => {
    switch (status) {
      case 'running':
        return '稼働中';
      case 'idle':
        return '待機';
      case 'stopped':
        return '停止';
      case 'error':
        return 'エラー';
      default:
        return '不明';
    }
  };

  const formatBytes = (bytes?: number) => {
    const value = Number(bytes ?? 0);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${Math.round(value)} B`;
  };

  const refetchQuery = async (snapshot?: { refetch?: () => Promise<unknown> }) => {
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  };

  let selectedModelId = $state('');
  let selectedDevice = $state('');
  let selectedTaskCandidate = $state('');
  let taskInput = $state('');
  let denoisingStepsInput = $state('10');
  let inferenceStartError = $state('');
  let inferenceStopError = $state('');
  let inferenceStartPending = $state(false);
  let inferenceStopPending = $state(false);
  let startupStatus = $state<StartupOperationStatusResponse | null>(null);
  let startupStreamError = $state('');
  let stopStartupStream = () => {};

  const START_PHASE_LABELS: Record<string, string> = {
    queued: 'キュー待機',
    resolve_profile: 'プロファイル解決',
    start_lerobot: 'Lerobot起動',
    sync_model: 'モデル同期',
    launch_worker: 'ワーカー起動',
    prepare_recorder: '録画準備',
    persist: '状態保存',
    done: '完了',
    error: '失敗'
  };

  const emptyRunnerStatus: RunnerStatus = {};
  const emptyGpuStatus: GpuHostStatus = {};

  $effect(() => {
    if (!selectedModelId && $inferenceModelsQuery.data?.models?.length) {
      selectedModelId = resolveModelId($inferenceModelsQuery.data.models[0]);
    }
  });

  $effect(() => {
    if (!selectedDevice && $inferenceDeviceQuery.data?.recommended) {
      selectedDevice = $inferenceDeviceQuery.data.recommended ?? '';
    }
  });

  const stopStartupStreamSubscription = () => {
    stopStartupStream();
    stopStartupStream = () => {};
  };

  const handleStartupStatusUpdate = async (status: StartupOperationStatusResponse) => {
    startupStatus = status;
    if (status.state === 'completed' && status.target_session_id) {
      stopStartupStreamSubscription();
      inferenceStartPending = false;
      await refetchQuery($inferenceRunnerStatusQuery);
      await goto(`/operate/sessions/${encodeURIComponent(status.target_session_id)}?kind=inference`);
      return;
    }
    if (status.state === 'failed') {
      inferenceStartPending = false;
      inferenceStartError = status.error ?? status.message ?? '推論の開始に失敗しました。';
    }
  };

  const subscribeStartupStream = (operationId: string) => {
    stopStartupStreamSubscription();
    startupStreamError = '';
    stopStartupStream = connectStream<StartupOperationStatusResponse>({
      path: `/api/stream/startup/operations/${encodeURIComponent(operationId)}`,
      onMessage: (payload) => {
        void handleStartupStatusUpdate(payload);
      },
      onError: () => {
        startupStreamError = '進捗ストリームが一時的に不安定です。再接続します...';
      }
    });
  };

  const handleInferenceStart = async () => {
    if (!selectedModelId) {
      inferenceStartError = '推論モデルを選択してください。';
      return;
    }
    startupStatus = null;
    startupStreamError = '';
    inferenceStartPending = true;
    inferenceStartError = '';
    inferenceStopError = '';
    let denoisingSteps: number | undefined;
    if (supportsDenoisingSteps) {
      const raw = denoisingStepsInput.trim();
      if (raw) {
        const parsed = Number.parseInt(raw, 10);
        if (!Number.isInteger(parsed) || parsed < 1) {
          inferenceStartError = 'denoising step は 1 以上の整数で入力してください。';
          inferenceStartPending = false;
          return;
        }
        denoisingSteps = parsed;
      }
    }
    const policyOptions =
      denoisingSteps === undefined
        ? undefined
        : selectedPolicyType === 'pi05'
          ? { pi05: { denoising_steps: denoisingSteps } }
          : { pi0: { denoising_steps: denoisingSteps } };
    try {
      const result = (await api.inference.runnerStart({
        model_id: selectedModelId,
        device: selectedDevice || $inferenceDeviceQuery.data?.recommended,
        task: taskInput.trim() || undefined,
        policy_options: policyOptions
      })) as StartupOperationAcceptedResponse;
      if (!result?.operation_id) {
        throw new Error('開始オペレーションIDを取得できませんでした。');
      }
      subscribeStartupStream(result.operation_id);
      const snapshot = await api.startup.operation(result.operation_id);
      await handleStartupStatusUpdate(snapshot);
    } catch (err) {
      inferenceStartError = err instanceof Error ? err.message : '推論の開始に失敗しました。';
      inferenceStartPending = false;
    }
  };

  const handleTaskCandidateSelect = (nextTask: string) => {
    selectedTaskCandidate = nextTask;
    taskInput = nextTask;
  };

  const handleTaskInput = (nextValue: string) => {
    taskInput = nextValue;
    selectedTaskCandidate = taskCandidates.includes(nextValue) ? nextValue : '';
  };

  const handleInferenceStop = async () => {
    inferenceStopPending = true;
    inferenceStopError = '';
    try {
      const runnerStatus = $inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus;
      const sessionId = runnerStatus.session_id;
      await api.inference.runnerStop({ session_id: sessionId });
      await refetchQuery($inferenceRunnerStatusQuery);
    } catch (err) {
      inferenceStopError = err instanceof Error ? err.message : '推論の停止に失敗しました。';
    } finally {
      inferenceStopPending = false;
    }
  };

  const runnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus);
  const gpuStatus = $derived($inferenceRunnerStatusQuery.data?.gpu_host_status ?? emptyGpuStatus);
  const selectedModel = $derived(
    ($inferenceModelsQuery.data?.models ?? []).find((item) => resolveModelId(item) === selectedModelId)
  );
  const selectedPolicyType = $derived((selectedModel?.policy_type ?? '').toLowerCase());
  const taskCandidates = $derived(selectedModel?.task_candidates ?? []);
  const supportsDenoisingSteps = $derived(PI0_POLICY_TYPES.has(selectedPolicyType));
  const runnerActive = $derived(Boolean(runnerStatus.active));
  const startupProgressPercent = $derived(
    Math.min(100, Math.max(0, Number(startupStatus?.progress_percent ?? 0)))
  );
  const startupState = $derived(startupStatus?.state ?? '');
  const startupActive = $derived(startupState === 'queued' || startupState === 'running');
  const showStartupBlock = $derived(Boolean(startupStatus) && (startupActive || startupState === 'failed'));
  const startupPhaseLabel = $derived(START_PHASE_LABELS[startupStatus?.phase ?? ''] ?? (startupStatus?.phase ?? '-'));
  const startupDetail = $derived(startupStatus?.detail ?? {});

  $effect(() => {
    selectedModelId;
    if (!taskCandidates.length) {
      selectedTaskCandidate = '';
      return;
    }
    if (!selectedTaskCandidate || !taskCandidates.includes(selectedTaskCandidate)) {
      selectedTaskCandidate = taskCandidates[0];
    }
    if (!taskInput.trim()) {
      taskInput = selectedTaskCandidate;
    }
  });

  $effect(() => {
    const stopOperateStream = connectStream<OperateStatusStreamPayload>({
      path: '/api/stream/operate/status',
      onMessage: (payload) => {
        queryClient.setQueryData(['inference', 'runner', 'status'], payload.inference_runner_status);
        queryClient.setQueryData(['operate', 'status'], payload.operate_status);
      }
    });

    return () => {
      stopOperateStream();
    };
  });

  $effect(() => {
    return () => {
      stopStartupStreamSubscription();
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Operate</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">推論</h1>
      <p class="mt-2 text-sm text-slate-600">推論セッションの確認と開始を行います。</p>
    </div>
  </div>
</section>

<ActiveSessionSection
  title="稼働中セッション"
  description="推論セッションの状況を表示します。"
  badges={[`推論: ${runnerActive ? '稼働中' : '停止'}`]}
>
  {#if $inferenceRunnerStatusQuery.isLoading}
    <ActiveSessionCard tone="muted">
      <p class="text-sm text-slate-600">推論セッションを読み込み中...</p>
    </ActiveSessionCard>
  {:else if runnerActive}
    <ActiveSessionCard>
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="label">セッション種別</p>
          <p class="text-base font-semibold text-slate-900">推論</p>
          <p class="mt-1 text-xs text-slate-500">モデル推論での実行セッション。</p>
        </div>
        <span class="chip">稼働中</span>
      </div>
      <div class="mt-3 space-y-1 text-xs text-slate-500">
        <p>session_id: {runnerStatus.session_id ?? '-'}</p>
        <p>task: {runnerStatus.task ?? '-'}</p>
        <p>queue: {runnerStatus.queue_length ?? 0}</p>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <Button.Root
          class="btn-primary"
          href={`/operate/sessions/${encodeURIComponent(runnerStatus.session_id ?? '')}?kind=inference`}
        >
          セッションを開く
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleInferenceStop} disabled={inferenceStopPending}>
          停止
        </Button.Root>
      </div>
      {#if runnerStatus.last_error}
        <p class="mt-2 text-xs text-rose-600">{runnerStatus.last_error}</p>
      {/if}
      {#if inferenceStopError}
        <p class="mt-2 text-xs text-rose-600">{inferenceStopError}</p>
      {/if}
    </ActiveSessionCard>
  {:else}
    <ActiveSessionCard tone="muted">
      <p class="text-sm text-slate-600">稼働中のセッションはありません。</p>
    </ActiveSessionCard>
  {/if}
</ActiveSessionSection>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">推論開始</h2>
      <p class="mt-1 text-sm text-slate-600">
        モデルとデバイスを選択して推論を開始します。
      </p>
    </div>
  </div>

  <div class="mt-4">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="label">推論</p>
          <h3 class="text-lg font-semibold text-slate-900">推論開始</h3>
        </div>
        <span class="chip">{runnerActive ? '稼働中' : '待機'}</span>
      </div>
      <div class="mt-4 grid gap-4 text-sm text-slate-600">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">推論モデル</span>
          <select class="input mt-2" bind:value={selectedModelId}>
            {#if $inferenceModelsQuery.isLoading}
              <option value="">読み込み中...</option>
            {:else if $inferenceModelsQuery.data?.models?.length}
              {#each $inferenceModelsQuery.data.models as model}
                {@const modelId = resolveModelId(model)}
                <option value={modelId}>
                  {model.name ?? modelId} ({model.policy_type ?? 'unknown'}){model.is_local ? '' : ' / 未同期'}
                </option>
              {/each}
            {:else}
              <option value="">モデルがありません</option>
            {/if}
          </select>
        </label>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="text-sm font-semibold text-slate-700">
            <span class="label">デバイス</span>
            <select class="input mt-2" bind:value={selectedDevice}>
              {#if $inferenceDeviceQuery.isLoading}
                <option value="">読み込み中...</option>
              {:else}
                {#each $inferenceDeviceQuery.data?.devices ?? [] as device}
                  <option value={device.device} disabled={!device.available}>
                    {device.device}{device.available ? '' : ' (不可)'}
                  </option>
                {/each}
                {#if !$inferenceDeviceQuery.data?.devices?.length}
                  <option value="cpu">cpu</option>
                {/if}
              {/if}
            </select>
            <p class="mt-2 text-xs text-slate-500">推奨: {$inferenceDeviceQuery.data?.recommended ?? 'cpu'}</p>
          </label>

          <div class="text-sm font-semibold text-slate-700">
            <span class="label">タスク説明</span>
            <div class="mt-2">
              <TaskCandidateCombobox
                items={taskCandidates}
                value={selectedTaskCandidate}
                inputValue={taskInput}
                placeholder="候補からタスクを選択"
                emptyMessage="このモデルで利用可能なタスク候補はありません。"
                onSelect={handleTaskCandidateSelect}
                onInput={handleTaskInput}
              />
            </div>
            {#if taskCandidates.length}
              <p class="mt-2 text-xs text-slate-500">
                候補選択または直接入力のどちらでもタスクを指定できます。
              </p>
            {:else}
              <p class="mt-2 text-xs text-slate-500">
                このモデルに紐づく active データセットのタスク候補はありません。直接入力してください。
              </p>
            {/if}
          </div>
        </div>
        {#if supportsDenoisingSteps}
          <label class="text-sm font-semibold text-slate-700">
            <span class="label">Denoising Step</span>
            <input
              class="input mt-2"
              type="text"
              inputmode="numeric"
              bind:value={denoisingStepsInput}
              placeholder="例: 10"
            />
            <p class="mt-2 text-xs text-slate-500">空欄の場合はモデル既定値を使用します。</p>
          </label>
        {/if}

        <div class="flex flex-wrap gap-3">
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleInferenceStart}
            disabled={inferenceStartPending || startupActive || !selectedModelId || runnerActive}
            aria-busy={inferenceStartPending}
          >
            {startupActive ? '準備中...' : '推論を開始'}
          </Button.Root>
        </div>
        {#if showStartupBlock}
          <div class="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
            <div class="flex items-center justify-between gap-3 text-xs text-emerald-800">
              <p>{startupStatus?.message ?? '推論セッションを準備中です...'}</p>
              <p class="font-semibold">{Math.round(startupProgressPercent)}%</p>
            </div>
            <p class="mt-1 text-xs text-emerald-900/80">フェーズ: {startupPhaseLabel}</p>
            <div class="mt-2 h-2 overflow-hidden rounded-full bg-emerald-100">
              <div
                class="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
                style={`width: ${startupProgressPercent}%;`}
              ></div>
            </div>
            {#if (startupDetail.total_files ?? 0) > 0 || (startupDetail.total_bytes ?? 0) > 0}
              <p class="mt-2 text-xs text-emerald-900/80">
                {startupDetail.files_done ?? 0}/{startupDetail.total_files ?? 0} files
                · {formatBytes(startupDetail.transferred_bytes)} / {formatBytes(startupDetail.total_bytes)}
                {#if startupDetail.current_file}
                  · {startupDetail.current_file}
                {/if}
              </p>
            {/if}
            {#if startupStreamError}
              <p class="mt-2 text-xs text-amber-700">{startupStreamError}</p>
            {/if}
          </div>
        {/if}
        {#if inferenceStartError}
          <p class="text-xs text-rose-600">{inferenceStartError}</p>
        {/if}
      </div>
    </div>
  </div>
</section>

<OperateStatusCards status={$operateStatusQuery.data} gpuLabel={renderGpuStatus(gpuStatus.status)} />
