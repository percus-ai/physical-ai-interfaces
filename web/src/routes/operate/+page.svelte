<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from 'svelte/store';
  import { api } from '$lib/api/client';

  type TeleopSessionsResponse = {
    sessions?: Array<{
      session_id?: string;
      mode?: string;
      leader_port?: string;
      follower_port?: string;
      is_running?: boolean;
    }>;
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

  type ProfileStatusResponse = {
    profile_id?: string;
    profile_class_key?: string;
    cameras?: Array<{
      name?: string;
      enabled?: boolean;
      connected?: boolean;
      topics?: string[];
    }>;
    arms?: Array<{
      name?: string;
      enabled?: boolean;
      connected?: boolean;
    }>;
  };

  type DevicesResponse = {
    leader_right?: { port?: string };
    follower_right?: { port?: string };
    cameras?: Record<string, unknown>;
  };

  const teleopSessionsQuery = createQuery<TeleopSessionsResponse>({
    queryKey: ['teleop', 'sessions'],
    queryFn: api.teleop.sessions
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
    queryFn: api.inference.runnerStatus,
    refetchInterval: 2000
  });

  const profileStatusQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status', 'operate'],
    queryFn: api.profiles.activeStatus,
    refetchInterval: 5000
  });

  const devicesQuery = createQuery<DevicesResponse>({
    queryKey: ['user', 'devices'],
    queryFn: api.user.devices
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

  const refetchQuery = async (queryStore: { subscribe: (run: (value: any) => void) => () => void }) => {
    const snapshot = get(queryStore);
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  };

  let selectedModelId = '';
  let selectedDevice = '';
  let task = '';
  let startError = '';
  let stopError = '';
  let startPending = false;
  let stopPending = false;
  const emptyRunnerStatus: RunnerStatus = {};
  const emptyGpuStatus: GpuHostStatus = {};

  $: if (!selectedModelId && $inferenceModelsQuery.data?.models?.length) {
    selectedModelId = resolveModelId($inferenceModelsQuery.data.models[0]);
  }

  $: if (!selectedDevice && $inferenceDeviceQuery.data?.recommended) {
    selectedDevice = $inferenceDeviceQuery.data.recommended ?? '';
  }

  const handleStart = async () => {
    if (!selectedModelId) {
      startError = '推論モデルを選択してください。';
      return;
    }
    startPending = true;
    startError = '';
    stopError = '';
    try {
      await api.inference.runnerStart({
        model_id: selectedModelId,
        device: selectedDevice || $inferenceDeviceQuery.data?.recommended,
        task: task.trim() || undefined
      });
      await refetchQuery(inferenceRunnerStatusQuery);
    } catch (err) {
      startError = err instanceof Error ? err.message : '推論の開始に失敗しました。';
    } finally {
      startPending = false;
    }
  };

  const handleStop = async () => {
    stopPending = true;
    stopError = '';
    try {
      const runnerStatus = $inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus;
      const sessionId = runnerStatus.session_id;
      await api.inference.runnerStop({ session_id: sessionId });
      await refetchQuery(inferenceRunnerStatusQuery);
    } catch (err) {
      stopError = err instanceof Error ? err.message : '推論の停止に失敗しました。';
    } finally {
      stopPending = false;
    }
  };

  $: runnerStatus = $inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus;
  $: gpuStatus = $inferenceRunnerStatusQuery.data?.gpu_host_status ?? emptyGpuStatus;
  $: runnerActive = Boolean(runnerStatus.active);
</script>

<section class="card-strong p-8">
  <p class="section-title">Operate</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">テレオペ / 推論</h1>
      <p class="mt-2 text-sm text-slate-600">テレオペレーションと推論セッションの状態を確認します。</p>
    </div>
    <div class="flex items-center gap-2">
      <span class="chip">Runner: {runnerActive ? '実行中' : '停止中'}</span>
      <span class="chip">GPU: {renderGpuStatus(gpuStatus.status)}</span>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">推論コントロール</h2>
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
          <p class="mt-2 text-xs text-slate-500">
            推奨: {$inferenceDeviceQuery.data?.recommended ?? 'cpu'}
          </p>
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
          onclick={handleStart}
          disabled={startPending || !selectedModelId || runnerActive}
          aria-busy={startPending}
        >
          推論を開始
        </Button.Root>
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={handleStop}
          disabled={stopPending || !runnerActive}
          aria-busy={stopPending}
        >
          推論を停止
        </Button.Root>
      </div>
      {#if startError}
        <p class="text-sm text-rose-600">{startError}</p>
      {/if}
      {#if stopError}
        <p class="text-sm text-rose-600">{stopError}</p>
      {/if}

      <div class="mt-2 rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <div class="flex items-center justify-between">
          <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">アクティブプロファイル</p>
          <span class="text-[10px] text-slate-400">{$profileStatusQuery.data?.profile_class_key ?? '-'}</span>
        </div>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <div class="space-y-2">
            <p class="label">Arms</p>
            {#each $profileStatusQuery.data?.arms ?? [] as arm}
              <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
                <span class="font-semibold text-slate-700">{arm.name ?? 'arm'}</span>
                <span class={`chip ${arm.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {arm.connected ? '接続' : '未接続'}
                </span>
              </div>
            {/each}
          </div>
          <div class="space-y-2">
            <p class="label">Cameras</p>
            {#each $profileStatusQuery.data?.cameras ?? [] as cam}
              <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
                <span class="font-semibold text-slate-700">{cam.name ?? 'camera'}</span>
                <span class={`chip ${cam.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {cam.connected ? '接続' : '未接続'}
                </span>
              </div>
            {/each}
          </div>
        </div>
        <p class="mt-3 text-xs text-slate-500">推論カメラは compressed トピックを使用します。</p>
      </div>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">推論ステータス</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $inferenceRunnerStatusQuery.isLoading}
        <p>読み込み中...</p>
      {:else}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <div class="flex items-center justify-between">
            <p class="font-semibold text-slate-800">Runner</p>
            <span class="chip">{runnerActive ? '実行中' : '停止'}</span>
          </div>
          <p class="mt-1 text-xs text-slate-500">session_id: {runnerStatus.session_id ?? '-'}</p>
          <p class="text-xs text-slate-500">task: {runnerStatus.task ?? '-'}</p>
          <p class="text-xs text-slate-500">queue: {runnerStatus.queue_length ?? 0}</p>
          {#if runnerStatus.last_error}
            <p class="mt-2 text-xs text-rose-600">{runnerStatus.last_error}</p>
          {/if}
        </div>

        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <div class="flex items-center justify-between">
            <p class="font-semibold text-slate-800">GPU Host</p>
            <span class="chip">{renderGpuStatus(gpuStatus.status)}</span>
          </div>
          <p class="mt-1 text-xs text-slate-500">session_id: {gpuStatus.session_id ?? '-'}</p>
          <p class="text-xs text-slate-500">pid: {gpuStatus.pid ?? '-'}</p>
          {#if gpuStatus.last_error}
            <p class="mt-2 text-xs text-rose-600">{gpuStatus.last_error}</p>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">テレオペレーション状態</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $teleopSessionsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $teleopSessionsQuery.data?.sessions?.length}
        {#each $teleopSessionsQuery.data.sessions as session}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div>
              <p class="font-semibold text-slate-800">{session.session_id}</p>
              <p class="text-xs text-slate-500">{session.mode} / {session.leader_port} → {session.follower_port}</p>
            </div>
            <span class="chip">{session.is_running ? '実行中' : '待機'}</span>
          </div>
        {/each}
      {:else}
        <p>稼働中のセッションはありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">デバイス設定</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">リーダー右腕</p>
        <p class="text-base font-semibold text-slate-800">
          {$devicesQuery.data?.leader_right?.port ?? '-'}
        </p>
      </div>
      <div>
        <p class="label">フォロワー右腕</p>
        <p class="text-base font-semibold text-slate-800">
          {$devicesQuery.data?.follower_right?.port ?? '-'}
        </p>
      </div>
      <div>
        <p class="label">カメラ</p>
        <p class="text-sm text-slate-600">
          {Object.keys($devicesQuery.data?.cameras ?? {}).length} 台登録
        </p>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">推論モデル一覧</h2>
  <div class="mt-4 space-y-3 text-sm text-slate-600">
    {#if $inferenceModelsQuery.isLoading}
      <p>読み込み中...</p>
    {:else if $inferenceModelsQuery.data?.models?.length}
      {#each $inferenceModelsQuery.data.models as model}
        <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <div>
            <p class="font-semibold text-slate-800">{model.name ?? model.model_id}</p>
            <p class="text-xs text-slate-500">{model.policy_type} / {model.source}</p>
          </div>
          <span class="chip">{model.is_local ? 'ローカル' : '未同期'}</span>
        </div>
      {/each}
    {:else}
      <p>利用可能なモデルがありません。</p>
    {/if}
  </div>
</section>
