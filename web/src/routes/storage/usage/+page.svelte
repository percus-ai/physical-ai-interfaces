<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes } from '$lib/format';

  type StorageUsageResponse = {
    datasets_size_bytes?: number;
    datasets_count?: number;
    models_size_bytes?: number;
    models_count?: number;
    archive_size_bytes?: number;
    archive_count?: number;
    total_size_bytes?: number;
  };

  const usageQuery = createQuery<StorageUsageResponse>({
    queryKey: ['storage', 'usage', 'page'],
    queryFn: api.storage.usage
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">ストレージ使用量</h1>
      <p class="mt-2 text-sm text-slate-600">ストレージの使用状況を一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      <Button.Root class="btn-ghost" href="/storage/archive">アーカイブ一覧</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">容量サマリ</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">データセット</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.datasets_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.datasets_count ?? 0}</p>
      </div>
      <div>
        <p class="label">モデル</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.models_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.models_count ?? 0}</p>
      </div>
      <div>
        <p class="label">アーカイブ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.archive_size_bytes)}</p>
        <p class="text-xs text-slate-500">件数: {$usageQuery.data?.archive_count ?? 0}</p>
      </div>
      <div>
        <p class="label">合計</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes($usageQuery.data?.total_size_bytes)}</p>
      </div>
    </div>
  </div>
</section>
