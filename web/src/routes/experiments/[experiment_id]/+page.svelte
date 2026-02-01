<script lang="ts">
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate } from '$lib/format';

  type Experiment = {
    id: string;
    model_id: string;
    profile_instance_id?: string | null;
    name?: string;
    purpose?: string | null;
    evaluation_count?: number;
    metric?: string;
    metric_options?: string[] | null;
    result_image_files?: string[] | null;
    notes?: string | null;
    created_at?: string;
    updated_at?: string;
  };

  type ModelSummary = {
    id: string;
    name?: string;
    dataset_id?: string;
  };

  type ProfileInstanceSummary = {
    id: string;
    name?: string;
    class_key?: string;
  };

  type DatasetSummary = {
    id: string;
    name?: string;
  };

  const DEFAULT_METRIC_OPTIONS = ['成功', '失敗', '部分成功'];

  const experimentQuery = createQuery<Experiment>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'detail', experimentId],
        queryFn: () => api.experiments.get(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  const modelsQuery = createQuery<{ models?: ModelSummary[] }>({
    queryKey: ['storage', 'models'],
    queryFn: api.storage.models
  });

  const profilesQuery = createQuery<{ instances?: ProfileInstanceSummary[] }>({
    queryKey: ['profiles', 'instances'],
    queryFn: api.profiles.instances
  });

  const datasetsQuery = createQuery<{ datasets?: DatasetSummary[] }>({
    queryKey: ['storage', 'datasets'],
    queryFn: () => api.storage.datasets()
  });

  let initializedId = '';
  let name = '';
  let purpose = '';
  let evaluationCount: number | string = 1;
  let metric = 'binary';
  let metricOptionsText = DEFAULT_METRIC_OPTIONS.join(', ');
  let notes = '';
  let resultImageFiles: string[] = [];
  let pendingFiles: FileList | null = null;
  let submitting = false;
  let error = '';
  let success = '';

  $: experiment = $experimentQuery.data as Experiment | undefined;
  $: modelMap = new Map(($modelsQuery.data?.models ?? []).map((model) => [model.id, model]));
  $: profileMap = new Map(
    ($profilesQuery.data?.instances ?? []).map((inst) => [inst.id, inst])
  );
  $: datasetMap = new Map(($datasetsQuery.data?.datasets ?? []).map((dataset) => [dataset.id, dataset]));

  const metricOptionsToText = (options?: string[] | null) => {
    if (!options || options.length === 0) return DEFAULT_METRIC_OPTIONS.join(', ');
    return options.join(', ');
  };

  $: if (experiment && experiment.id !== initializedId) {
    name = experiment.name ?? '';
    purpose = experiment.purpose ?? '';
    evaluationCount = experiment.evaluation_count ?? 1;
    metric = experiment.metric ?? 'binary';
    metricOptionsText = metricOptionsToText(experiment.metric_options ?? null);
    notes = experiment.notes ?? '';
    resultImageFiles = experiment.result_image_files ?? [];
    pendingFiles = null;
    error = '';
    success = '';
    initializedId = experiment.id;
  }

  const parseMetricOptions = (text: string) => {
    const items = text
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    return items.length ? items : null;
  };

  const handleUpdate = async () => {
    if (!experiment) return;
    submitting = true;
    error = '';
    success = '';
    let imageFiles = [...resultImageFiles];

    try {
      if (pendingFiles && pendingFiles.length) {
        const formData = new FormData();
        Array.from(pendingFiles).forEach((file) => {
          formData.append('files', file);
        });
        const upload = await api.experiments.upload(experiment.id, formData, { scope: 'experiment' });
        if (upload?.keys?.length) {
          imageFiles = [...imageFiles, ...upload.keys];
        }
      }

      const payload = {
        name,
        purpose: purpose || null,
        evaluation_count: Number(evaluationCount) || 1,
        metric,
        metric_options: parseMetricOptions(metricOptionsText),
        result_image_files: imageFiles,
        notes: notes || null
      };
      const updated = await api.experiments.update(experiment.id, payload);
      resultImageFiles = updated.result_image_files ?? imageFiles;
      pendingFiles = null;
      success = '実験を更新しました。';
    } catch {
      error = '更新に失敗しました。';
    } finally {
      submitting = false;
    }
  };

  const handleDelete = async () => {
    if (!experiment) return;
    if (!confirm('この実験を削除しますか？')) return;
    try {
      await api.experiments.delete(experiment.id);
      await goto('/experiments');
    } catch {
      error = '削除に失敗しました。';
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">実験詳細</h1>
      <p class="mt-2 text-sm text-slate-600">ID: {experiment?.id ?? '-'}</p>
      <p class="mt-1 text-xs text-slate-500">更新: {formatDate(experiment?.updated_at)}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/experiments">一覧へ</Button.Root>
      {#if experiment?.id}
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/evaluations`}>評価入力</Button.Root>
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/analyses`}>考察入力</Button.Root>
      {/if}
    </div>
  </div>
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
  <div class="mt-4 grid gap-4">
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">実験名</span>
      <input class="input mt-2" type="text" bind:value={name} />
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">実験目的</span>
      <textarea class="input mt-2 min-h-[96px]" bind:value={purpose}></textarea>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">評価回数</span>
      <input class="input mt-2" type="number" min="1" step="1" bind:value={evaluationCount} />
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">評価指標</span>
      <input class="input mt-2" type="text" bind:value={metric} />
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">評価候補（カンマ区切り）</span>
      <input class="input mt-2" type="text" bind:value={metricOptionsText} />
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">結果画像アップロード</span>
      <input
        class="input mt-2"
        type="file"
        multiple
        accept="image/*"
        bind:files={pendingFiles}
      />
    </label>
    <div class="text-sm text-slate-600">
      <p class="label">既存画像キー</p>
      <pre class="mt-2 max-h-40 overflow-auto rounded-xl border border-slate-200/70 bg-white/70 p-3 text-xs">{resultImageFiles.length ? resultImageFiles.join('\n') : 'なし'}</pre>
    </div>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">備考</span>
      <textarea class="input mt-2 min-h-[96px]" bind:value={notes}></textarea>
    </label>
    {#if error}
      <p class="text-sm text-rose-600">{error}</p>
    {/if}
    {#if success}
      <p class="text-sm text-emerald-600">{success}</p>
    {/if}
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-primary" type="button" onclick={handleUpdate} disabled={submitting}>
        更新
      </Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={handleDelete}>削除</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">参照情報（編集不可）</h2>
  <div class="mt-4 grid gap-3 text-sm text-slate-600">
    <div>
      <p class="label">モデル</p>
      <p class="mt-1 font-semibold text-slate-800">
        {experiment?.model_id ? modelMap.get(experiment.model_id)?.name ?? experiment.model_id : '-'}
      </p>
    </div>
    <div>
      <p class="label">環境</p>
      <p class="mt-1 font-semibold text-slate-800">
        {experiment?.profile_instance_id
          ? profileMap.get(experiment.profile_instance_id)?.class_key ??
            profileMap.get(experiment.profile_instance_id)?.name ??
            experiment.profile_instance_id
          : '未設定'}
      </p>
    </div>
    <div>
      <p class="label">データセット</p>
      <p class="mt-1 font-semibold text-slate-800">
        {modelMap.get(experiment?.model_id ?? '')?.dataset_id
          ? datasetMap.get(modelMap.get(experiment?.model_id ?? '')?.dataset_id ?? '')?.name ??
            modelMap.get(experiment?.model_id ?? '')?.dataset_id
          : '-'}
      </p>
    </div>
  </div>
</section>
