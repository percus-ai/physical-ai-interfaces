<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api/client';
  import GpuAvailabilityBoard from '$lib/components/training/GpuAvailabilityBoard.svelte';
  import { getBackendUrl } from '$lib/config';
  import { formatBytes, formatDate } from '$lib/format';
  import { GPU_COUNTS, GPU_MODELS, POLICY_TYPES } from '$lib/policies';
  import type { GpuAvailabilityResponse } from '$lib/types/training';

  type DatasetSummary = {
    id: string;
    name?: string;
    profile_name?: string;
    dataset_type?: string;
    status?: string;
    created_at?: string;
    size_bytes?: number;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['datasets', 'train'],
    queryFn: () => api.storage.datasets()
  });

  const gpuAvailabilityQuery = createQuery<GpuAvailabilityResponse>({
    queryKey: ['training', 'gpu-availability'],
    queryFn: api.training.gpuAvailability
  });

  const gpuModelOrder = $derived(GPU_MODELS.map((gpu) => gpu.name));

  const defaultPolicy = POLICY_TYPES[0];
  let policyType = $state(defaultPolicy?.id ?? '');

  let steps = $state(defaultPolicy?.defaultSteps ?? 100000);
  let batchSize = $state(defaultPolicy?.defaultBatchSize ?? 32);
  let saveFreq = $state(defaultPolicy?.defaultSaveFreq ?? 5000);
  let logFreq = $state(200);
  let numWorkers = $state(4);
  let saveCheckpoint = $state(true);

  let validationEnable = $state(true);
  let validationEvalFreq = $state(100);
  let validationMaxBatches = $state(0);
  let validationBatchSize = $state(0);

  let earlyStoppingEnable = $state(true);
  let earlyStoppingPatience = $state(5);
  let earlyStoppingMinDelta = $state(0.002);
  let earlyStoppingMode = $state<'min' | 'max'>('min');

  let datasetVideoBackend = $state<'auto' | 'torchcodec' | 'pyav'>('torchcodec');
  let selectedPretrainedId = $state('');

  let policyDtype = $state<'auto' | 'float32' | 'bfloat16' | 'float16'>('auto');
  let policyUseAmp = $state<'auto' | 'true' | 'false'>('auto');
  let policyGradientCheckpointing = $state<'auto' | 'true' | 'false'>('auto');
  let policyCompileModel = $state<'auto' | 'true' | 'false'>('auto');

  let gpuModel = $state(defaultPolicy?.recommendedGpu ?? 'H100');
  let gpuCount = $state(GPU_COUNTS[0] ?? 1);
  let storageSize = $state(defaultPolicy?.recommendedStorage ?? 100);
  let instanceType = $state<'spot' | 'ondemand'>('spot');

  let jobName = $state('');

  let submitting = $state(false);
  let submitError = $state('');
  let createStage = $state('待機中');
  let createMessage = $state('');
  let createStatus = $state<'idle' | 'running' | 'complete' | 'error'>('idle');
  let createEvents = $state<Array<{ type: string; message: string; timestamp: string }>>([]);
  let createWs = $state<WebSocket | null>(null);

  let selectedDataset = $state('');

  const applyPolicyDefaults = (policyId: string) => {
    const info = POLICY_TYPES.find((policy) => policy.id === policyId);
    if (!info) return;
    steps = info.defaultSteps;
    batchSize = info.defaultBatchSize;
    saveFreq = info.defaultSaveFreq;
    storageSize = info.recommendedStorage;
    gpuModel = info.recommendedGpu;
    logFreq = info.defaultLogFreq;
    numWorkers = info.defaultNumWorkers;
    saveCheckpoint = true;
    validationEnable = true;
    validationEvalFreq = 100;
    validationMaxBatches = 0;
    validationBatchSize = 0;
    earlyStoppingEnable = true;
    earlyStoppingPatience = 5;
    earlyStoppingMinDelta = 0.002;
    earlyStoppingMode = 'min';

    policyDtype = info.dtype ? (info.dtype as typeof policyDtype) : 'auto';
    policyCompileModel = info.compileModel === undefined ? 'auto' : info.compileModel ? 'true' : 'false';
    policyGradientCheckpointing =
      info.gradientCheckpointing === undefined ? 'auto' : info.gradientCheckpointing ? 'true' : 'false';
    if (policyDtype === 'bfloat16') {
      policyUseAmp = 'false';
    } else {
      policyUseAmp = info.useAmp === undefined ? 'auto' : info.useAmp ? 'true' : 'false';
    }

    if (policyId === 'pi05') {
      validationEvalFreq = Math.min(500, steps);
      earlyStoppingMinDelta = 0.002;
    }
  };

  const handlePolicyChange = (event: Event) => {
    const value = (event.target as HTMLSelectElement).value;
    policyType = value;
    applyPolicyDefaults(value);
  };

  const isTrainingDataset = (dataset: DatasetSummary) => {
    const datasetId = dataset.id ?? '';
    const datasetType = dataset.dataset_type;
    if (datasetType === 'eval' || datasetId.includes('/eval_')) return false;
    if (dataset.status === 'archived') return false;
    return Boolean(datasetId);
  };

  const policyInfo = $derived(POLICY_TYPES.find((policy) => policy.id === policyType) ?? null);
  const pretrainedOptions = $derived(policyInfo?.pretrainedModels ?? []);

  $effect(() => {
    if (policyInfo?.skipPretrained || pretrainedOptions.length === 0) {
      if (selectedPretrainedId) {
        selectedPretrainedId = '';
      }
      return;
    }
    if (!pretrainedOptions.some((option) => option.id === selectedPretrainedId)) {
      selectedPretrainedId = pretrainedOptions[0]?.id ?? '';
    }
  });

  const selectedPretrained = $derived(
    pretrainedOptions.find((option) => option.id === selectedPretrainedId) ?? null
  );

  const datasets = $derived($datasetsQuery.data?.datasets?.filter(isTrainingDataset) ?? []);
  const datasetsSorted = $derived(
    datasets.slice().sort(
      (a, b) =>
        new Date((b.created_at as string | undefined) ?? 0).getTime() -
        new Date((a.created_at as string | undefined) ?? 0).getTime()
    )
  );

  $effect(() => {
    if (datasetsSorted.length && !selectedDataset) {
      selectedDataset = datasetsSorted[0].id as string;
      return;
    }
    if (selectedDataset && datasetsSorted.length && !datasetsSorted.some((s) => s.id === selectedDataset)) {
      selectedDataset = datasetsSorted[0].id as string;
    }
  });

  const selectedDatasetInfo = $derived(
    datasetsSorted.find((dataset) => dataset.id === selectedDataset) ?? null
  );
  const datasetShortId = $derived(selectedDatasetInfo?.id?.slice(0, 6) ?? '');

  $effect(() => {
    if (!validationEnable && earlyStoppingEnable) {
      earlyStoppingEnable = false;
    }
  });

  const useAmpDisabled = $derived(policyDtype === 'bfloat16');
  const isSpot = $derived(instanceType === 'spot');

  const wsUrl = (path: string) => getBackendUrl().replace(/^http/, 'ws') + path;

  const progressLabelMap: Record<string, string> = {
    start: '開始',
    validating: '設定検証',
    validated: '設定検証',
    selecting_instance: 'インスタンス選択',
    instance_selected: 'インスタンス選択',
    finding_location: 'ロケーション探索',
    location_found: 'ロケーション探索',
    creating_instance: 'インスタンス作成',
    instance_created: 'インスタンス作成',
    waiting_ip: 'IP割り当て待機',
    ip_assigned: 'IP割り当て完了',
    waiting_running: 'インスタンス起動待機',
    instance_running: 'インスタンス起動完了',
    connecting_ssh: 'SSH接続',
    ssh_ready: 'SSH接続完了',
    deploying: 'ファイル転送',
    setting_up: '環境構築',
    starting_training: '学習開始',
    complete: '完了',
    error: 'エラー'
  };

  const buildJobName = (policy: string, shortId: string) => {
    const now = new Date();
    const pad = (value: number) => value.toString().padStart(2, '0');
    const timestamp = `${pad(now.getFullYear() % 100)}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
      now.getHours()
    )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const parts = [] as string[];
    if (policy) parts.push(policy);
    if (shortId) parts.push(shortId);
    parts.push(timestamp);
    return parts.join('_');
  };

  const generatedJobName = $derived(buildJobName(policyType, datasetShortId));

  const toBool = (value: 'auto' | 'true' | 'false') => {
    if (value === 'auto') return null;
    return value === 'true';
  };

  const buildPayload = () => {
    if (!selectedDataset) return null;
    const name = jobName.trim() || generatedJobName;

    const payload: Record<string, unknown> = {
      job_name: name,
      dataset: {
        id: selectedDataset,
        source: 'r2'
      },
      policy: {
        type: policyType
      },
      training: {
        steps,
        batch_size: batchSize,
        save_freq: saveFreq,
        log_freq: logFreq,
        num_workers: numWorkers,
        save_checkpoint: saveCheckpoint
      },
      validation: {
        enable: validationEnable
      },
      early_stopping: {
        enable: earlyStoppingEnable,
        patience: earlyStoppingPatience,
        min_delta: earlyStoppingMinDelta,
        mode: earlyStoppingMode
      },
      cloud: {
        gpu_model: gpuModel,
        gpus_per_instance: gpuCount,
        storage_size: storageSize,
        is_spot: isSpot
      },
      wandb_enable: false,
      sync_dataset: false
    };

    if (selectedPretrained?.path) {
      (payload.policy as Record<string, unknown>).pretrained_path = selectedPretrained.path;
    }
    if (datasetVideoBackend !== 'auto') {
      (payload.dataset as Record<string, unknown>).video_backend = datasetVideoBackend;
    }

    if (validationEnable) {
      const validationPayload = payload.validation as Record<string, unknown>;
      validationPayload.eval_freq = validationEvalFreq;
      validationPayload.max_batches = validationMaxBatches > 0 ? validationMaxBatches : null;
      validationPayload.batch_size = validationBatchSize > 0 ? validationBatchSize : null;
    }

    const policyPayload = payload.policy as Record<string, unknown>;
    if (policyDtype !== 'auto') policyPayload.dtype = policyDtype;

    const ampSetting = useAmpDisabled ? 'false' : policyUseAmp;
    const useAmpValue = toBool(ampSetting);
    const gradValue = toBool(policyGradientCheckpointing);
    const compileValue = toBool(policyCompileModel);

    if (useAmpValue !== null) policyPayload.use_amp = useAmpValue;
    if (gradValue !== null) policyPayload.gradient_checkpointing = gradValue;
    if (compileValue !== null) policyPayload.compile_model = compileValue;

    return payload;
  };

  const submit = async () => {
    submitError = '';
    createStatus = 'idle';
    const payload = buildPayload();
    if (!payload) {
      submitError = 'データセットを選択してください。';
      return;
    }
    submitting = true;
    createStatus = 'running';
    createStage = '開始';
    createMessage = '';
    createEvents = [];

    if (createWs) {
      createWs.close();
    }

    let accessToken = '';
    try {
      const auth = await api.auth.token();
      accessToken = auth.access_token;
    } catch (error) {
      createStatus = 'error';
      submitError = 'セッション情報を取得できませんでした。ログインし直してください。';
      submitting = false;
      return;
    }

    const ws = new WebSocket(
      wsUrl(`/api/training/ws/create-job?access_token=${encodeURIComponent(accessToken)}`)
    );
    createWs = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = async (event) => {
      const data = JSON.parse(event.data as string) as { type?: string; message?: string; error?: string; job_id?: string };
      if (data.type === 'heartbeat') return;
      const type = data.type ?? 'status';
      const label = progressLabelMap[type] ?? type;
      const message = data.message || data.error || label;
      createStage = label;
      createMessage = message;
      createEvents = [
        ...createEvents,
        { type, message, timestamp: new Date().toLocaleTimeString('ja-JP') }
      ].slice(-12);

      if (type === 'error') {
        createStatus = 'error';
        submitError = data.error || '学習ジョブの作成に失敗しました。';
        submitting = false;
        ws.close();
      }

      if (type === 'complete') {
        createStatus = 'complete';
        submitting = false;
        ws.close();
        if (data.job_id) {
          await goto(`/train/jobs/${data.job_id}`);
        }
      }
    };

    ws.onerror = () => {
      createStatus = 'error';
      submitError = 'WebSocket接続に失敗しました。';
      submitting = false;
    };

    ws.onclose = () => {
      if (createStatus === 'running') {
        createStatus = 'error';
        submitError = '接続が切断されました。';
        submitting = false;
      }
      createWs = null;
    };
  };

  const availability = $derived($gpuAvailabilityQuery.data?.available ?? []);

  onDestroy(() => {
    createWs?.close();
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">新規学習</h1>
      <p class="mt-2 text-sm text-slate-600">1ページで学習ジョブを設定して開始します。</p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-ghost" href="/train">一覧へ戻る</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
  <div class="space-y-6">
    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ポリシー</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ポリシータイプ</span>
          <select class="input mt-2" bind:value={policyType} onchange={handlePolicyChange}>
            {#each POLICY_TYPES as policy}
              <option value={policy.id}>{policy.displayName}</option>
            {/each}
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">事前学習済みモデル</span>
          <select
            class="input mt-2"
            bind:value={selectedPretrainedId}
            disabled={policyInfo?.skipPretrained || pretrainedOptions.length === 0}
          >
            {#if policyInfo?.skipPretrained || pretrainedOptions.length === 0}
              <option value="">このポリシーは事前学習不要</option>
            {:else}
              {#each pretrainedOptions as model}
                <option value={model.id}>{model.name}</option>
              {/each}
            {/if}
          </select>
          {#if selectedPretrained?.description}
            <p class="mt-2 text-xs text-slate-500">{selectedPretrained.description}</p>
          {/if}
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">データセット</span>
          <select class="input mt-2" bind:value={selectedDataset}>
            {#if datasetsSorted.length}
              {#each datasetsSorted as dataset}
                <option value={dataset.id}>
                  {dataset.name ?? dataset.id} (profile: {dataset.profile_name ?? '-'})
                </option>
              {/each}
            {:else}
              <option value="">データセットがありません</option>
            {/if}
          </select>
        </label>
      </div>
      <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p class="label">選択中のデータセット</p>
            <p class="mt-2 font-semibold text-slate-800">
              {selectedDatasetInfo?.name ?? selectedDatasetInfo?.id ?? '-'}
            </p>
            <p class="text-xs text-slate-500">
              profile: {selectedDatasetInfo?.profile_name ?? '-'}
            </p>
          </div>
          <div>
            <p class="label">サイズ / 作成日時</p>
            <p class="mt-2 font-semibold text-slate-800">
              {formatBytes(selectedDatasetInfo?.size_bytes ?? 0)} / {formatDate(selectedDatasetInfo?.created_at)}
            </p>
          </div>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">Video backend</span>
          <select class="input mt-2" bind:value={datasetVideoBackend}>
            <option value="auto">自動 (torchcodec優先)</option>
            <option value="torchcodec">torchcodec</option>
            <option value="pyav">pyav</option>
          </select>
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">学習パラメータ</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ステップ数</span>
          <input class="input mt-2" type="number" min="100" bind:value={steps} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">バッチサイズ</span>
          <input class="input mt-2" type="number" min="1" bind:value={batchSize} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">保存頻度</span>
          <input class="input mt-2" type="number" min="50" bind:value={saveFreq} />
        </label>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ログ頻度</span>
          <input class="input mt-2" type="number" min="1" bind:value={logFreq} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">DataLoader workers</span>
          <input class="input mt-2" type="number" min="0" bind:value={numWorkers} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">チェックポイント保存</span>
          <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" bind:checked={saveCheckpoint} />
            <span>{saveCheckpoint ? '有効' : '無効'}</span>
          </div>
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">検証 / Early Stopping</h2>
      <div class="mt-4 text-sm font-semibold text-slate-700">
        <span class="label">検証を有効</span>
        <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" bind:checked={validationEnable} />
          <span>{validationEnable ? '有効' : '無効'}</span>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">検証頻度</span>
          <input
            class="input mt-2"
            type="number"
            min="1"
            bind:value={validationEvalFreq}
            disabled={!validationEnable}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">検証バッチサイズ</span>
          <input
            class="input mt-2"
            type="number"
            min="0"
            bind:value={validationBatchSize}
            disabled={!validationEnable}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">検証バッチ数上限</span>
          <input
            class="input mt-2"
            type="number"
            min="0"
            bind:value={validationMaxBatches}
            disabled={!validationEnable}
          />
        </label>
      </div>

      <div class="divider my-6"></div>

      <div class="text-sm font-semibold text-slate-700">
        <span class="label">Early Stopping</span>
        <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" bind:checked={earlyStoppingEnable} disabled={!validationEnable} />
          <span>{earlyStoppingEnable ? '有効' : '無効'}</span>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">モード</span>
          <select class="input mt-2" bind:value={earlyStoppingMode} disabled={!earlyStoppingEnable}>
            <option value="min">min</option>
            <option value="max">max</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">Patience</span>
          <input
            class="input mt-2"
            type="number"
            min="1"
            bind:value={earlyStoppingPatience}
            disabled={!earlyStoppingEnable}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">min_delta</span>
          <input
            class="input mt-2"
            type="number"
            step="0.0001"
            bind:value={earlyStoppingMinDelta}
            disabled={!earlyStoppingEnable}
          />
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">モデル設定</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">dtype</span>
          <select class="input mt-2" bind:value={policyDtype}>
            <option value="auto">指定しない</option>
            <option value="float32">float32</option>
            <option value="bfloat16">bfloat16</option>
            <option value="float16">float16</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">AMP</span>
          <select class="input mt-2" bind:value={policyUseAmp} disabled={useAmpDisabled}>
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
          {#if useAmpDisabled}
            <p class="mt-2 text-xs text-slate-500">bfloat16 選択時は AMP を無効化します。</p>
          {/if}
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">Gradient checkpointing</span>
          <select class="input mt-2" bind:value={policyGradientCheckpointing}>
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">torch.compile</span>
          <select class="input mt-2" bind:value={policyCompileModel}>
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
        </label>
      </div>
    </section>
  </div>

  <div class="space-y-6">
    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">クラウド設定</h2>
      <div class="mt-4 grid gap-4">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">GPUモデル</span>
          <select class="input mt-2" bind:value={gpuModel}>
            {#each GPU_MODELS as gpu}
              <option value={gpu.name}>{gpu.name} - {gpu.description}</option>
            {/each}
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">GPU数</span>
          <select class="input mt-2" bind:value={gpuCount}>
            {#each GPU_COUNTS as count}
              <option value={count}>{count} GPU</option>
            {/each}
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ストレージ (GB)</span>
          <input class="input mt-2" type="number" min="1" bind:value={storageSize} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">インスタンス種別</span>
          <div class="mt-3 grid gap-2 text-sm text-slate-600">
            <label class="flex items-center gap-2">
              <input type="radio" name="instanceType" value="spot" bind:group={instanceType} />
              <span>スポット</span>
            </label>
            <label class="flex items-center gap-2">
              <input type="radio" name="instanceType" value="ondemand" bind:group={instanceType} />
              <span>オンデマンド</span>
            </label>
          </div>
        </label>
      </div>
      <div class="mt-4">
        <p class="label mb-2">空き状況</p>
        <GpuAvailabilityBoard
          items={availability}
          loading={$gpuAvailabilityQuery.isLoading}
          selectedGpuModel={gpuModel}
          selectedGpuCount={gpuCount}
          showOnlyAvailableDefault={true}
          preferredModelOrder={gpuModelOrder}
        />
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ジョブ名と実行</h2>
      <div class="mt-4 grid gap-4">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ジョブ名 (空で自動生成)</span>
          <input class="input mt-2" bind:value={jobName} placeholder={generatedJobName} />
        </label>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
          <p class="label">プレビュー</p>
          <p class="mt-2 font-semibold text-slate-800">{jobName.trim() || generatedJobName}</p>
        </div>
        {#if submitError}
          <p class="text-sm text-rose-600">{submitError}</p>
        {/if}
        <Button.Root class="btn-primary" type="button" onclick={submit} disabled={submitting}>
          {submitting ? '作成中...' : '学習を開始'}
        </Button.Root>
        {#if submitting || createEvents.length}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
            <div class="flex items-center justify-between">
              <p class="label">作成進行</p>
              <span class="chip">{createStage}</span>
            </div>
            <p class="mt-2 text-sm text-slate-700">{createMessage || '進行状況を取得中...'}</p>
            <div class="mt-3 space-y-1">
              {#each createEvents as event}
                <p class="text-xs text-slate-500">[{event.timestamp}] {event.message}</p>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </section>
  </div>
</section>
