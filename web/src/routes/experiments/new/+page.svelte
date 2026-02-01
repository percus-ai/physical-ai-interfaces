<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  type ModelSummary = {
    id: string;
    name?: string;
  };

  type ProfileInstanceSummary = {
    id: string;
    name?: string;
    class_key?: string;
  };

  const DEFAULT_METRIC_OPTIONS = ['成功', '失敗', '部分成功'];

  const modelsQuery = createQuery<{ models?: ModelSummary[] }>({
    queryKey: ['storage', 'models'],
    queryFn: api.storage.models
  });

  const profilesQuery = createQuery<{ instances?: ProfileInstanceSummary[] }>({
    queryKey: ['profiles', 'instances'],
    queryFn: api.profiles.instances
  });

  const pad = (value: number) => String(value).padStart(2, '0');
  const defaultName = () => {
    const now = new Date();
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
      now.getHours()
    )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  };

  let modelId = '';
  let profileInstanceId = '';
  let name = defaultName();
  let purpose = '';
  let evaluationCount: number | string = 10;
  let metric = 'binary';
  let metricOptionsText = DEFAULT_METRIC_OPTIONS.join(', ');
  let notes = '';
  let submitting = false;
  let error = '';

  $: if (!modelId && $modelsQuery.data?.models?.length) {
    modelId = $modelsQuery.data.models[0].id;
  }

  const parseMetricOptions = (text: string) => {
    const items = text
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    return items.length ? items : null;
  };

  const handleSubmit = async () => {
    if (!modelId) {
      error = 'モデルを選択してください。';
      return;
    }
    submitting = true;
    error = '';
    try {
      const payload = {
        model_id: modelId,
        profile_instance_id: profileInstanceId || null,
        name: name || defaultName(),
        purpose: purpose || null,
        evaluation_count: Number(evaluationCount) || 1,
        metric,
        metric_options: parseMetricOptions(metricOptionsText),
        notes: notes || null
      };
      const result = await api.experiments.create(payload);
      await goto(`/experiments/${result.id}`);
    } catch (err) {
      error = '実験の作成に失敗しました。';
    } finally {
      submitting = false;
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">実験を作成</h1>
      <p class="mt-2 text-sm text-slate-600">モデルとプロフィールを選択して新しい実験を登録します。</p>
    </div>
    <Button.Root class="btn-ghost" href="/experiments">一覧に戻る</Button.Root>
  </div>
</section>

<section class="card p-6">
  <form class="grid gap-4" on:submit|preventDefault={handleSubmit}>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">モデル</span>
      <select class="input mt-2" bind:value={modelId}>
        {#if !$modelsQuery.data?.models?.length}
          <option value="">モデルがありません</option>
        {:else}
          {#each $modelsQuery.data?.models ?? [] as model}
            <option value={model.id}>{model.name ?? model.id}</option>
          {/each}
        {/if}
      </select>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">プロフィール（任意）</span>
      <select class="input mt-2" bind:value={profileInstanceId}>
        <option value="">未設定</option>
        {#each $profilesQuery.data?.instances ?? [] as inst}
          <option value={inst.id}>{inst.class_key}:{inst.name ?? 'active'}</option>
        {/each}
      </select>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">実験名</span>
      <input class="input mt-2" type="text" bind:value={name} required />
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
      <span class="label">備考</span>
      <textarea class="input mt-2 min-h-[96px]" bind:value={notes}></textarea>
    </label>
    {#if error}
      <p class="text-sm text-rose-600">{error}</p>
    {/if}
    <div class="mt-2 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" type="submit" disabled={submitting} aria-busy={submitting}>
        作成
      </Button.Root>
      <Button.Root class="btn-ghost" href="/experiments">キャンセル</Button.Root>
    </div>
  </form>
</section>
