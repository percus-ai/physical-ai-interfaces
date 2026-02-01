<script lang="ts">
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { Button, Tooltip } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatPercent } from '$lib/format';

  type Experiment = {
    id: string;
    name?: string;
    evaluation_count?: number;
    metric_options?: string[] | null;
  };

  type Evaluation = {
    trial_index: number;
    value?: string;
    notes?: string | null;
    image_files?: string[] | null;
  };

  type EvaluationListResponse = {
    evaluations?: Evaluation[];
    total?: number;
  };

  type EvaluationSummary = {
    total?: number;
    counts?: Record<string, number>;
    rates?: Record<string, number>;
  };

  type MediaUrlResponse = {
    urls?: Record<string, string>;
  };

  type EvaluationDraft = {
    trial_index: number;
    value: string;
    selection: string;
    custom: string;
    notes: string;
    image_files: string[];
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

  const evaluationsQuery = createQuery<EvaluationListResponse>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'evaluations', experimentId],
        queryFn: () => api.experiments.evaluations(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  const summaryQuery = createQuery<EvaluationSummary>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'summary', experimentId],
        queryFn: () => api.experiments.evaluationSummary(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  let evaluationItems: EvaluationDraft[] = [];
  let initializedId = '';
  let submitting = false;
  let error = '';
  let success = '';
  let uploadingIndex: number | null = null;
  let uploadError = '';
  let imageUrlsError = '';
  let imageUrlMap: Record<string, string> = {};
  let imageKeySignature = '';

  $: experiment = $experimentQuery.data as Experiment | undefined;
  $: evaluationCount = experiment?.evaluation_count ?? 0;
  $: metricOptions =
    experiment?.metric_options && experiment.metric_options.length
      ? experiment.metric_options
      : DEFAULT_METRIC_OPTIONS;

  const buildEvaluationDrafts = (exp: Experiment, existing: Evaluation[]) => {
    const map = new Map(existing.map((item) => [item.trial_index, item]));
    const drafts: EvaluationDraft[] = [];
    for (let index = 1; index <= (exp.evaluation_count ?? 0); index += 1) {
      const row = map.get(index);
      const currentValue = row?.value ?? '';
      const isCustom = currentValue ? !metricOptions.includes(currentValue) : true;
      drafts.push({
        trial_index: index,
        value: currentValue,
        selection: isCustom ? 'その他' : currentValue,
        custom: isCustom ? currentValue : '',
        notes: row?.notes ?? '',
        image_files: row?.image_files ?? []
      });
    }
    return drafts;
  };

  const resetFromServer = () => {
    if (!experiment) return;
    const existing = $evaluationsQuery.data?.evaluations ?? [];
    evaluationItems = buildEvaluationDrafts(experiment, existing);
  };

  $: if (experiment && $evaluationsQuery.data && experiment.id !== initializedId) {
    resetFromServer();
    initializedId = experiment.id;
  }

  $: filledCount = evaluationItems.filter((item) => item.value.trim()).length;
  $: remainingCount = Math.max(0, (experiment?.evaluation_count ?? 0) - filledCount);
  $: imageKeys = Array.from(
    new Set(evaluationItems.flatMap((item) => item.image_files ?? []).filter(Boolean))
  );

  $: if (imageKeys.join('|') !== imageKeySignature) {
    imageKeySignature = imageKeys.join('|');
    void loadImageUrls();
  }

  const updateItem = (index: number, updates: Partial<EvaluationDraft>) => {
    evaluationItems = evaluationItems.map((item, idx) =>
      idx === index ? { ...item, ...updates } : item
    );
  };

  const handleSelect = (index: number, value: string) => {
    if (value === 'その他') {
      const custom = evaluationItems[index]?.custom ?? '';
      updateItem(index, { selection: value, value: custom });
    } else {
      updateItem(index, { selection: value, value });
    }
  };

  const handleCustomInput = (index: number, value: string) => {
    if (evaluationItems[index]?.selection === 'その他') {
      updateItem(index, { custom: value, value });
    } else {
      updateItem(index, { custom: value });
    }
  };

  const handleNotesInput = (index: number, value: string) => {
    updateItem(index, { notes: value });
  };

  const handleRemoveImage = (index: number, key: string) => {
    const next = (evaluationItems[index]?.image_files ?? []).filter((item) => item !== key);
    updateItem(index, { image_files: next });
  };

  const handleUpload = async (index: number, event: Event) => {
    if (!experiment) return;
    const input = event.currentTarget as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (!files.length) return;

    uploadingIndex = index;
    uploadError = '';
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));
      const response = await api.experiments.upload(experiment.id, formData, {
        scope: 'evaluation',
        trial_index: index + 1
      });
      if (response?.keys?.length) {
        const existing = evaluationItems[index]?.image_files ?? [];
        updateItem(index, { image_files: [...existing, ...response.keys] });
      }
      input.value = '';
    } catch {
      uploadError = '画像アップロードに失敗しました。';
    } finally {
      uploadingIndex = null;
    }
  };

  const formatRates = (rates?: Record<string, number>) => {
    if (!rates || Object.keys(rates).length === 0) return '-';
    return Object.entries(rates)
      .map(([key, value]) => `${key}: ${formatPercent(value)}`)
      .join(' / ');
  };

  const refetchSummary = async () => {
    const refetch = $summaryQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const refetchEvaluations = async () => {
    const refetch = $evaluationsQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const loadImageUrls = async () => {
    if (!imageKeys.length) {
      imageUrlMap = {};
      imageUrlsError = '';
      return;
    }
    try {
      const response = (await api.experiments.mediaUrls(imageKeys)) as MediaUrlResponse;
      imageUrlMap = response?.urls ?? {};
      imageUrlsError = '';
    } catch {
      imageUrlsError = '画像URLの取得に失敗しました。';
    }
  };

  const handleSave = async () => {
    if (!experiment) return;
    submitting = true;
    error = '';
    success = '';
    try {
      const items = evaluationItems.map((item) => ({
        value: item.value ?? '',
        notes: item.notes || null,
        image_files: item.image_files
      }));
      await api.experiments.replaceEvaluations(experiment.id, { items });
      await refetchSummary();
      await refetchEvaluations();
      resetFromServer();
      success = '評価を保存しました。';
    } catch {
      error = '評価の保存に失敗しました。';
    } finally {
      submitting = false;
    }
  };

  const handleClear = async () => {
    if (!experiment) return;
    if (!confirm('評価を全て削除しますか？')) return;
    submitting = true;
    error = '';
    success = '';
    try {
      await api.experiments.replaceEvaluations(experiment.id, { items: [] });
      await refetchSummary();
      await refetchEvaluations();
      resetFromServer();
      success = '評価を削除しました。';
    } catch {
      error = '評価の削除に失敗しました。';
    } finally {
      submitting = false;
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">評価入力</h1>
      <p class="mt-2 text-sm text-slate-600">{experiment?.name ?? experiment?.id ?? ''}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if experiment?.id}
        <Tooltip.Root>
          <Tooltip.Trigger class="btn-ghost" type={null}>
            {#snippet child({ props })}
              <Button.Root {...props} href={`/experiments/${experiment.id}`}>開く</Button.Root>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content
              class="rounded-lg bg-slate-900/90 px-2 py-1 text-xs text-white shadow-lg"
              sideOffset={6}
            >
              {experiment?.name ?? experiment?.id}
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/analyses`}>考察入力へ</Button.Root>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="text-xl font-semibold text-slate-900">評価一覧</h2>
      <div class="flex flex-wrap gap-2">
        <Button.Root class="btn-ghost" type="button" onclick={resetFromServer}>最新を反映</Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleClear}>全削除</Button.Root>
      </div>
    </div>

    {#if uploadError}
      <p class="mt-3 text-sm text-rose-600">{uploadError}</p>
    {/if}
    {#if imageUrlsError}
      <p class="mt-3 text-sm text-rose-600">{imageUrlsError}</p>
    {/if}
    {#if error}
      <p class="mt-3 text-sm text-rose-600">{error}</p>
    {/if}
    {#if success}
      <p class="mt-3 text-sm text-emerald-600">{success}</p>
    {/if}

    <div class="mt-4 space-y-4">
      {#if $evaluationsQuery.isLoading}
        <p class="text-sm text-slate-500">読み込み中...</p>
      {:else if evaluationItems.length}
        {#each evaluationItems as item, index}
          <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-sm">
            <div class="flex items-center justify-between">
              <p class="font-semibold text-slate-800">試行 {item.trial_index}</p>
              <span class="chip">#{item.trial_index}</span>
            </div>
            <div class="mt-3 grid gap-3 md:grid-cols-2">
              <label class="text-sm font-semibold text-slate-700">
                <span class="label">評価値</span>
                <select
                  class="input mt-2"
                  value={item.selection}
                  on:change={(event) => handleSelect(index, (event.currentTarget as HTMLSelectElement).value)}
                >
                  {#each metricOptions as option}
                    <option value={option}>{option}</option>
                  {/each}
                  <option value="その他">その他</option>
                </select>
                {#if item.selection === 'その他'}
                  <input
                    class="input mt-2"
                    type="text"
                    placeholder="自由入力"
                    value={item.custom}
                    on:input={(event) =>
                      handleCustomInput(index, (event.currentTarget as HTMLInputElement).value)
                    }
                  />
                {/if}
              </label>
              <label class="text-sm font-semibold text-slate-700">
                <span class="label">備考</span>
                <input
                  class="input mt-2"
                  type="text"
                  value={item.notes}
                  on:input={(event) =>
                    handleNotesInput(index, (event.currentTarget as HTMLInputElement).value)
                  }
                />
              </label>
            </div>
            <div class="mt-3 text-sm text-slate-600">
              <p class="label">画像プレビュー</p>
              {#if item.image_files.length}
                <div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {#each item.image_files as key}
                    <div class="group relative">
                      {#if imageUrlMap[key]}
                        <img
                          src={imageUrlMap[key]}
                          alt={`評価画像 ${item.trial_index}`}
                          class="h-20 w-full rounded-lg border border-slate-200/60 object-cover"
                          loading="lazy"
                        />
                      {:else}
                        <div class="flex h-20 items-center justify-center rounded-lg border border-dashed border-slate-200/70 bg-white/70 text-xs text-slate-400">
                          準備中
                        </div>
                      {/if}
                      <Button.Root
                        class="absolute right-1 top-1 rounded-full bg-slate-900/80 px-2 py-1 text-[10px] font-semibold text-white opacity-0 transition group-hover:opacity-100"
                        type="button"
                        onclick={() => handleRemoveImage(index, key)}
                        aria-label="画像を削除"
                        title="削除"
                      >
                        削除
                      </Button.Root>
                    </div>
                  {/each}
                </div>
              {:else}
                <p class="mt-2 text-xs text-slate-400">画像はありません。</p>
              {/if}
              <input
                class="input mt-2"
                type="file"
                accept="image/*"
                multiple
                disabled={uploadingIndex === index}
                on:change={(event) => handleUpload(index, event)}
              />
            </div>
          </div>
        {/each}
      {:else}
        <p class="text-sm text-slate-500">評価項目がありません。</p>
      {/if}
    </div>

    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" type="button" onclick={handleSave} disabled={submitting}>
        保存
      </Button.Root>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">集計</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">入力済み</p>
        <p class="text-base font-semibold text-slate-800">{filledCount} / {evaluationCount}</p>
        <p class="text-xs text-slate-500">未入力: {remainingCount}</p>
      </div>
      <div>
        <p class="label">保存済み評価件数</p>
        <p class="text-base font-semibold text-slate-800">{$summaryQuery.data?.total ?? 0}</p>
      </div>
      <div>
        <p class="label">カテゴリ比率</p>
        <p class="text-sm font-semibold text-slate-800">{formatRates($summaryQuery.data?.rates)}</p>
      </div>
    </div>
  </div>
</section>
