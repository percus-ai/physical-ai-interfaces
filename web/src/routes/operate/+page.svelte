<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import ActiveSessionSection from '$lib/components/ActiveSessionSection.svelte';
  import ActiveSessionCard from '$lib/components/ActiveSessionCard.svelte';

  type InferenceModel = {
    model_id?: string;
    name?: string;
    policy_type?: string;
    source?: string;
    size_mb?: number;
    is_loaded?: boolean;
    is_local?: boolean;
  };

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

  const refetchQuery = async (snapshot?: { refetch?: () => Promise<unknown> }) => {
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  };

  let selectedModelId = $state('');
  let selectedDevice = $state('');
  let task = $state('');
  let inferenceStartError = $state('');
  let inferenceStopError = $state('');
  let inferenceStartPending = $state(false);
  let inferenceStopPending = $state(false);

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

  const handleInferenceStart = async () => {
    if (!selectedModelId) {
      inferenceStartError = '推論モデルを選択してください。';
      return;
    }
    inferenceStartPending = true;
    inferenceStartError = '';
    inferenceStopError = '';
    try {
      const result = (await api.inference.runnerStart({
        model_id: selectedModelId,
        device: selectedDevice || $inferenceDeviceQuery.data?.recommended,
        task: task.trim() || undefined
      })) as { session_id?: string };
      await refetchQuery($inferenceRunnerStatusQuery);
      const nextSessionId =
        result?.session_id ?? ($inferenceRunnerStatusQuery.data?.runner_status?.session_id ?? '');
      if (nextSessionId) {
        await goto(`/operate/sessions/${encodeURIComponent(nextSessionId)}?kind=inference`);
      }
    } catch (err) {
      inferenceStartError = err instanceof Error ? err.message : '推論の開始に失敗しました。';
    } finally {
      inferenceStartPending = false;
    }
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
  const runnerActive = $derived(Boolean(runnerStatus.active));

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
                  {model.name ?? modelId} ({model.policy_type ?? 'unknown'})
                </option>
              {/each}
            {:else}
              <option value="">モデルがありません</option>
            {/if}
          </select>
          <p class="mt-2 text-xs text-slate-500">モデルがローカルに存在しない場合は先に同期してください。</p>
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

          <label class="text-sm font-semibold text-slate-700">
            <span class="label">タスク説明</span>
            <input class="input mt-2" type="text" bind:value={task} placeholder="例: 物体を掴んで箱に置く" />
          </label>
        </div>

        <div class="flex flex-wrap gap-3">
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleInferenceStart}
            disabled={inferenceStartPending || !selectedModelId || runnerActive}
            aria-busy={inferenceStartPending}
          >
            推論を開始
          </Button.Root>
        </div>
        {#if inferenceStartError}
          <p class="text-xs text-rose-600">{inferenceStartError}</p>
        {/if}
      </div>
    </div>
  </div>
</section>

<OperateStatusCards status={$operateStatusQuery.data} gpuLabel={renderGpuStatus(gpuStatus.status)} />
