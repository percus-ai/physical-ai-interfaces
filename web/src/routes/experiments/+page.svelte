<script lang="ts">
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate, formatPercent } from '$lib/format';
  import { goto } from '$app/navigation';

  type ModelSummary = {
    id: string;
    name?: string;
    dataset_id?: string;
  };

  type EnvironmentSummary = {
    id: string;
    name?: string;
  };

  type Experiment = {
    id: string;
    model_id: string;
    environment_id?: string | null;
    name?: string;
    evaluation_count?: number;
    updated_at?: string;
  };

  type ExperimentListResponse = {
    experiments?: Experiment[];
    total?: number;
  };

  type EvaluationSummary = {
    total?: number;
    rates?: Record<string, number>;
  };

  type AnalysisListResponse = {
    analyses?: Array<{ id?: string }>;
    total?: number;
  };

  const modelsQuery = createQuery<{ models?: ModelSummary[] }>({
    queryKey: ['storage', 'models'],
    queryFn: api.storage.models
  });

  const environmentsQuery = createQuery<{ environments?: EnvironmentSummary[] }>({
    queryKey: ['storage', 'environments'],
    queryFn: api.storage.environments
  });

  let selectedModel = '';
  let selectedEnvironment = '';

  const experimentsQuery = createQuery<ExperimentListResponse>({
    queryKey: ['experiments', selectedModel, selectedEnvironment],
    queryFn: () =>
      api.experiments.list({
        model_id: selectedModel || undefined,
        environment_id: selectedEnvironment || undefined
      })
  });

  let summaryById: Record<string, EvaluationSummary> = {};
  let analysisById: Record<string, number> = {};
  let summariesLoading = false;
  let summariesError = '';
  let summaryKey = '';
  let experimentsError = '';

  $: experiments = $experimentsQuery.data?.experiments ?? [];
  $: experimentsError =
    $experimentsQuery.isError
      ? $experimentsQuery.error instanceof Error
        ? $experimentsQuery.error.message
        : '実験一覧の取得に失敗しました。'
      : '';
  $: displayCount = experimentsError ? '-' : String(experiments.length);
  $: {
    const key = experiments.map((exp) => exp.id).join('|');
    if (key !== summaryKey) {
      summaryKey = key;
      void loadSummaries();
    }
  }

  const loadSummaries = async () => {
    if (!experiments.length) {
      summaryById = {};
      analysisById = {};
      summariesError = '';
      return;
    }
    summariesLoading = true;
    summariesError = '';

    const nextSummary: Record<string, EvaluationSummary> = {};
    const nextAnalysis: Record<string, number> = {};
    let hasError = false;

    await Promise.all(
      experiments.map(async (exp) => {
        try {
          const [summary, analyses] = await Promise.all([
            api.experiments.evaluationSummary(exp.id) as Promise<EvaluationSummary>,
            api.experiments.analyses(exp.id) as Promise<AnalysisListResponse>
          ]);
          nextSummary[exp.id] = summary ?? {};
          nextAnalysis[exp.id] = analyses?.total ?? analyses?.analyses?.length ?? 0;
        } catch {
          hasError = true;
        }
      })
    );

    summaryById = nextSummary;
    analysisById = nextAnalysis;
    summariesLoading = false;
    if (hasError) {
      summariesError = '集計情報の取得に失敗しました。';
    }
  };

  const formatRates = (rates?: Record<string, number>) => {
    if (!rates || Object.keys(rates).length === 0) return '-';
    return Object.values(rates)
      .map((value) => formatPercent(value))
      .join(' / ');
  };

  const resetFilters = () => {
    selectedModel = '';
    selectedEnvironment = '';
  };

  const refreshAll = async () => {
    const refetch = $experimentsQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
    await loadSummaries();
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">実験管理</h1>
      <p class="mt-2 text-sm text-slate-600">実験の一覧・評価・考察をまとめて管理します。</p>
    </div>
    <Button.Root class="btn-primary" href="/experiments/new">実験を作成</Button.Root>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">フィルタ</h2>
      <p class="text-xs text-slate-500">モデル・環境で絞り込みできます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <button class="btn-ghost" type="button" on:click={resetFilters}>リセット</button>
      <button class="btn-ghost" type="button" on:click={refreshAll}>更新</button>
    </div>
  </div>
  <div class="mt-4 grid gap-4 md:grid-cols-3">
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">モデル</span>
      <select class="input mt-2" bind:value={selectedModel}>
        <option value="">すべて</option>
        {#each $modelsQuery.data?.models ?? [] as model}
          <option value={model.id}>{model.name ?? model.id}</option>
        {/each}
      </select>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">環境</span>
      <select class="input mt-2" bind:value={selectedEnvironment}>
        <option value="">すべて</option>
        {#each $environmentsQuery.data?.environments ?? [] as env}
          <option value={env.id}>{env.name ?? env.id}</option>
        {/each}
      </select>
    </label>
    <div class="text-sm text-slate-600">
      <p class="label">表示件数</p>
      <p class="mt-2 text-xl font-semibold text-slate-800">{displayCount}</p>
      {#if summariesLoading}
        <p class="mt-1 text-xs text-slate-500">集計を取得中...</p>
      {:else if summariesError}
        <p class="mt-1 text-xs text-rose-600">{summariesError}</p>
      {/if}
      {#if experimentsError}
        <p class="mt-1 text-xs text-rose-600">{experimentsError}</p>
      {/if}
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">実験一覧</h2>
    <span class="text-xs text-slate-500">更新: {formatDate(experiments[0]?.updated_at)}</span>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">実験名</th>
          <th class="pb-3">モデル</th>
          <th class="pb-3">環境</th>
          <th class="pb-3">評価回数</th>
          <th class="pb-3">評価件数</th>
          <th class="pb-3">カテゴリ比率</th>
          <th class="pb-3">考察</th>
          <th class="pb-3">更新日時</th>
          <th class="pb-3">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $experimentsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if experimentsError}
          <tr><td class="py-3" colspan="9">実験一覧の取得に失敗しました。</td></tr>
        {:else if experiments.length}
          {#each experiments as exp}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">{exp.name ?? '-'}</td>
              <td class="py-3">
                <a class="text-xs font-semibold text-brand underline underline-offset-2" href={`/storage/models/${exp.model_id}`}>開く</a>
              </td>
              <td class="py-3">
                {#if exp.environment_id}
                  <a class="text-xs font-semibold text-brand underline underline-offset-2" href={`/storage/environments/${exp.environment_id}`}>開く</a>
                {:else}
                  <span class="text-xs text-slate-400">未設定</span>
                {/if}
              </td>
              <td class="py-3">{exp.evaluation_count ?? 0}</td>
              <td class="py-3">{summariesLoading ? '-' : summaryById[exp.id]?.total ?? 0}</td>
              <td class="py-3">{summariesLoading ? '-' : formatRates(summaryById[exp.id]?.rates)}</td>
              <td class="py-3">{summariesLoading ? '-' : analysisById[exp.id] ? 'あり' : 'なし'}</td>
              <td class="py-3">{formatDate(exp.updated_at)}</td>
              <td class="py-3">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger class="btn-ghost text-xs">操作</DropdownMenu.Trigger>
                  <DropdownMenu.Content
                    class="z-50 min-w-[140px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
                    sideOffset={6}
                    align="end"
                  >
                    <DropdownMenu.Item
                      class="cursor-pointer rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                      onSelect={() => goto(`/experiments/${exp.id}`)}
                    >
                      詳細
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      class="cursor-pointer rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                      onSelect={() => goto(`/experiments/${exp.id}/evaluations`)}
                    >
                      評価
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      class="cursor-pointer rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                      onSelect={() => goto(`/experiments/${exp.id}/analyses`)}
                    >
                      考察
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">実験がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>
