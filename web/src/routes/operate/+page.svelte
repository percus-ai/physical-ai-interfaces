<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  type TeleopSession = {
    session_id?: string;
    mode?: string;
    leader_port?: string;
    follower_port?: string;
    fps?: number;
    is_running?: boolean;
    errors?: number;
  };

  type TeleopSessionsResponse = {
    sessions?: TeleopSession[];
    total?: number;
  };

  type TeleopProfileConfigResponse = {
    config?: {
      profile_id?: string;
      profile_class_key?: string;
      leader_port?: string;
      follower_port?: string;
      mode?: string;
      fps?: number;
      robot_preset?: string;
    };
  };

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

  const teleopSessionsQuery = createQuery<TeleopSessionsResponse>({
    queryKey: ['teleop', 'sessions'],
    queryFn: api.teleop.sessions
  });

  const teleopProfileConfigQuery = createQuery<TeleopProfileConfigResponse>({
    queryKey: ['teleop', 'profile-config'],
    queryFn: api.teleop.profileConfig
  });

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

  const renderStatusLabel = (status?: string) => {
    switch (status) {
      case 'running':
      case 'healthy':
        return '正常';
      case 'degraded':
        return '注意';
      case 'stopped':
        return '停止';
      case 'error':
        return 'エラー';
      default:
        return '不明';
    }
  };

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

  let teleopStartError = $state('');
  let teleopStopError = $state('');
  let teleopStartPending = $state(false);
  let teleopStopPending = $state(false);

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

  const handleTeleopStart = async () => {
    teleopStartPending = true;
    teleopStartError = '';
    teleopStopError = '';
    try {
      const result = (await api.teleop.startProfile()) as { session?: { session_id?: string } };
      const sessionId = result?.session?.session_id;
      await refetchQuery($teleopSessionsQuery);
      if (sessionId) {
        await goto(`/operate/sessions/${encodeURIComponent(sessionId)}?kind=teleop`);
      }
    } catch (err) {
      teleopStartError = err instanceof Error ? err.message : 'テレオペ開始に失敗しました。';
    } finally {
      teleopStartPending = false;
    }
  };

  const handleTeleopStop = async (sessionId?: string) => {
    if (!sessionId) return;
    teleopStopPending = true;
    teleopStopError = '';
    try {
      await api.teleop.stopLocal({ session_id: sessionId });
      await refetchQuery($teleopSessionsQuery);
    } catch (err) {
      teleopStopError = err instanceof Error ? err.message : 'テレオペ停止に失敗しました。';
    } finally {
      teleopStopPending = false;
    }
  };

  const runnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus);
  const gpuStatus = $derived($inferenceRunnerStatusQuery.data?.gpu_host_status ?? emptyGpuStatus);
  const runnerActive = $derived(Boolean(runnerStatus.active));

  const teleopSessions = $derived($teleopSessionsQuery.data?.sessions ?? []);
  const runningTeleopSessions = $derived(teleopSessions.filter((session) => session.is_running));
  const hasRunningTeleop = $derived(runningTeleopSessions.length > 0);

  const teleopLocked = $derived(runnerActive);
  const inferenceLocked = $derived(hasRunningTeleop);

  const profileConfig = $derived($teleopProfileConfigQuery.data?.config);
  const teleopConfigReady = $derived(Boolean(profileConfig?.leader_port && profileConfig?.follower_port));
  const networkDetails = $derived($operateStatusQuery.data?.network?.details ?? {});
  const driverDetails = $derived($operateStatusQuery.data?.driver?.details ?? {});

  $effect(() => {
    const stopOperateStream = connectStream({
      path: '/api/stream/operate/status',
      onMessage: (payload) => {
        queryClient.setQueryData(['teleop', 'sessions'], payload.teleop_sessions);
        queryClient.setQueryData(['teleop', 'profile-config'], payload.teleop_profile_config);
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
      <h1 class="text-3xl font-semibold text-slate-900">テレオペ / 推論</h1>
      <p class="mt-2 text-sm text-slate-600">運用中セッションの確認と開始をまとめて行います。</p>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">稼働中セッション</h2>
      <p class="mt-1 text-sm text-slate-600">テレオペ/推論をセッション単位でまとめて表示します。</p>
    </div>
    <div class="flex items-center gap-2">
      <span class="chip">テレオペ: {hasRunningTeleop ? '稼働中' : '停止'}</span>
      <span class="chip">推論: {runnerActive ? '稼働中' : '停止'}</span>
    </div>
  </div>

  <div class="mt-4 grid gap-4 lg:grid-cols-2">
    {#if $teleopSessionsQuery.isLoading}
      <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
        <p class="text-sm text-slate-600">テレオペセッションを読み込み中...</p>
      </div>
    {:else}
      {#each runningTeleopSessions as session}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <p class="label">セッション種別</p>
              <p class="text-base font-semibold text-slate-900">テレオペ</p>
              <p class="mt-1 text-xs text-slate-500">オペレータ操作での制御セッション。</p>
            </div>
            <span class="chip">稼働中</span>
          </div>
          <div class="mt-3 space-y-1 text-xs text-slate-500">
            <p>session_id: {session.session_id ?? '-'}</p>
            <p>
              {session.mode ?? 'simple'} / {session.leader_port ?? '-'} → {session.follower_port ?? '-'}
            </p>
            <p>fps: {session.fps ?? '-'}</p>
            <p>errors: {session.errors ?? 0}</p>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <Button.Root
              class="btn-primary"
              href={`/operate/sessions/${encodeURIComponent(session.session_id ?? '')}?kind=teleop`}
            >
              セッションを開く
            </Button.Root>
            <Button.Root
              class="btn-ghost"
              type="button"
              onclick={() => handleTeleopStop(session.session_id)}
              disabled={teleopStopPending}
            >
              停止
            </Button.Root>
          </div>
        </div>
      {/each}
    {/if}

    {#if $inferenceRunnerStatusQuery.isLoading}
      <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
        <p class="text-sm text-slate-600">推論セッションを読み込み中...</p>
      </div>
    {:else if runnerActive}
      <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
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
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={handleInferenceStop}
            disabled={inferenceStopPending}
          >
            停止
          </Button.Root>
        </div>
        {#if runnerStatus.last_error}
          <p class="mt-2 text-xs text-rose-600">{runnerStatus.last_error}</p>
        {/if}
        {#if inferenceStopError}
          <p class="mt-2 text-xs text-rose-600">{inferenceStopError}</p>
        {/if}
      </div>
    {/if}
  </div>

  {#if !hasRunningTeleop && !runnerActive && !$teleopSessionsQuery.isLoading && !$inferenceRunnerStatusQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">稼働中のセッションはありません。</p>
  {/if}
  {#if teleopStopError}
    <p class="mt-2 text-xs text-rose-600">{teleopStopError}</p>
  {/if}
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">セッション開始</h2>
      <p class="mt-1 text-sm text-slate-600">
        テレオペ/推論のいずれかを選択して開始します（同時稼働はできません）。
      </p>
    </div>
    <span class="chip">同時稼働不可</span>
  </div>

  <div class="mt-4 grid gap-4 lg:grid-cols-2">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="label">テレオペ</p>
          <h3 class="text-lg font-semibold text-slate-900">テレオペ開始</h3>
        </div>
        <span class="chip">{hasRunningTeleop ? '稼働中' : '待機'}</span>
      </div>
      <div class="mt-4 grid gap-4 text-sm text-slate-600">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="text-xs text-slate-500">Active profile</p>
          <p class="text-base font-semibold text-slate-800">
            {profileConfig?.profile_class_key ?? 'unknown'}
          </p>
          <p class="mt-2 text-xs text-slate-500">
            {profileConfig?.leader_port ?? '-'} → {profileConfig?.follower_port ?? '-'}
          </p>
          <p class="text-xs text-slate-500">
            mode: {profileConfig?.mode ?? 'simple'} / fps: {profileConfig?.fps ?? 60}
          </p>
        </div>
        {#if !teleopConfigReady}
          <p class="text-xs text-rose-600">プロファイルのポート設定が不足しています。</p>
        {:else if teleopLocked}
          <p class="text-xs text-amber-600">推論が稼働中のため、テレオペ開始はできません。</p>
        {:else if hasRunningTeleop}
          <p class="text-xs text-amber-600">既にテレオペセッションが稼働中です。</p>
        {/if}
        <div class="flex flex-wrap gap-2">
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleTeleopStart}
            disabled={teleopStartPending || teleopLocked || hasRunningTeleop || !teleopConfigReady}
            aria-busy={teleopStartPending}
          >
            テレオペ開始
          </Button.Root>
        </div>
        {#if teleopStartError}
          <p class="text-xs text-rose-600">{teleopStartError}</p>
        {/if}
      </div>
    </div>

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

        {#if inferenceLocked}
          <p class="text-xs text-amber-600">テレオペが稼働中のため、推論開始はできません。</p>
        {/if}
        <div class="flex flex-wrap gap-3">
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleInferenceStart}
            disabled={inferenceStartPending || !selectedModelId || runnerActive || inferenceLocked}
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

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">バックエンド / ROS2 / ネットワーク / ドライバ</h2>
    <span class="chip">GPU: {renderGpuStatus(gpuStatus.status)}</span>
  </div>
  <div class="mt-4 grid gap-4 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-5">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Backend</p>
      <p class="mt-1 text-base font-semibold text-slate-800">
        {renderStatusLabel($operateStatusQuery.data?.backend?.status)}
      </p>
      <p class="text-xs text-slate-500">{$operateStatusQuery.data?.backend?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">VLABOR (ROS2)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">
        {renderStatusLabel($operateStatusQuery.data?.vlabor?.status)}
      </p>
      <p class="text-xs text-slate-500">{$operateStatusQuery.data?.vlabor?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">LeRobot (ROS2)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">
        {renderStatusLabel($operateStatusQuery.data?.lerobot?.status)}
      </p>
      <p class="text-xs text-slate-500">{$operateStatusQuery.data?.lerobot?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Network</p>
      <p class="mt-1 text-base font-semibold text-slate-800">
        {renderStatusLabel($operateStatusQuery.data?.network?.status)}
      </p>
      <div class="mt-2 text-xs text-slate-500 space-y-1">
        <p>Zenoh: {networkDetails?.zenoh?.status ?? '-'}</p>
        <p>rosbridge: {networkDetails?.rosbridge?.status ?? '-'}</p>
        <p>ZMQ: {networkDetails?.zmq?.status ?? '-'}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Driver (CUDA)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">
        {renderStatusLabel($operateStatusQuery.data?.driver?.status)}
      </p>
      <div class="mt-2 text-xs text-slate-500 space-y-1">
        <p>torch: {driverDetails?.torch_version ?? '-'}</p>
        <p>cuda: {driverDetails?.cuda_available ? 'available' : 'unavailable'}</p>
        <p>gpu: {driverDetails?.gpu_name ?? '-'}</p>
      </div>
    </div>
  </div>
</section>
