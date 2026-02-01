<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ModelSummary = {
    id: string;
    project_id?: string;
    policy_type?: string;
    dataset_id?: string;
    size_bytes?: number;
    status?: string;
    created_at?: string;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  type DatasetSummary = {
    id: string;
    name?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: ['storage', 'models', 'manage'],
    queryFn: api.storage.models
  });

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['storage', 'datasets', 'lookup'],
    queryFn: () => api.storage.datasets()
  });

  $: models = $modelsQuery.data?.models ?? [];
  $: datasetMap = new Map(
    ($datasetsQuery.data?.datasets ?? []).map((dataset) => [
      dataset.id,
      dataset.name ?? dataset.id
    ])
  );

  const displayModelId = (id: string, projectId?: string | null) => {
    if (projectId) {
      const prefixes = [`${projectId}/`, `${projectId}_`, `${projectId}-`];
      const matched = prefixes.find((prefix) => id.startsWith(prefix));
      if (matched) {
        return id.slice(matched.length) || id;
      }
    }
    return id.split('/').pop() ?? id;
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなモデルを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      <button class="btn-ghost" type="button" on:click={() => $modelsQuery?.refetch?.()}>
        更新
      </button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">ID</th>
          <th class="pb-3">プロジェクト</th>
          <th class="pb-3">ポリシー</th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">状態</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3"></th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan="8">読み込み中...</td></tr>
        {:else if models.length}
          {#each models as model}
            <tr class="border-t border-slate-200/60">
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={model.id}>
                  {displayModelId(model.id, model.project_id)}
                </span>
              </td>
              <td class="py-3">{model.project_id}</td>
              <td class="py-3">{model.policy_type ?? '-'}</td>
              <td class="py-3">
                {#if model.dataset_id}
                  <a
                    class="text-brand hover:underline"
                    href={`/storage/datasets/${model.dataset_id}`}
                    title={datasetMap.get(model.dataset_id) ?? model.dataset_id}
                  >
                    詳細
                  </a>
                {:else}
                  -
                {/if}
              </td>
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3"><span class="chip">{model.status}</span></td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              <td class="py-3 text-right">
                <Button.Root class="btn-ghost" href={`/storage/models/${model.id}`}>詳細</Button.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="8">モデルがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>
