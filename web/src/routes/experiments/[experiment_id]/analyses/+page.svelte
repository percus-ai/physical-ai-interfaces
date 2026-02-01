<script lang="ts">
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { Button, Tooltip } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  type Experiment = {
    id: string;
    name?: string;
  };

  type AnalysisBlock = {
    name?: string | null;
    purpose?: string | null;
    notes?: string | null;
    image_files?: string[] | null;
  };

  type MediaUrlResponse = {
    urls?: Record<string, string>;
  };

  type AnalysisListResponse = {
    analyses?: AnalysisBlock[];
    total?: number;
  };

  type AnalysisDraft = {
    name: string;
    purpose: string;
    notes: string;
    image_files: string[];
  };

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

  const analysesQuery = createQuery<AnalysisListResponse>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'analyses', experimentId],
        queryFn: () => api.experiments.analyses(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  let analysisBlocks: AnalysisDraft[] = [];
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

  const fromServer = () => {
    const blocks = $analysesQuery.data?.analyses ?? [];
    analysisBlocks = blocks.map((block) => ({
      name: block.name ?? '',
      purpose: block.purpose ?? '',
      notes: block.notes ?? '',
      image_files: block.image_files ?? []
    }));
  };

  $: if (experiment && $analysesQuery.data && experiment.id !== initializedId) {
    fromServer();
    initializedId = experiment.id;
  }

  const updateBlock = (index: number, updates: Partial<AnalysisDraft>) => {
    analysisBlocks = analysisBlocks.map((block, idx) =>
      idx === index ? { ...block, ...updates } : block
    );
  };

  const addBlock = () => {
    analysisBlocks = [...analysisBlocks, { name: '', purpose: '', notes: '', image_files: [] }];
  };

  const removeBlock = (index: number) => {
    analysisBlocks = analysisBlocks.filter((_, idx) => idx !== index);
  };

  const handleRemoveImage = (index: number, key: string) => {
    const next = (analysisBlocks[index]?.image_files ?? []).filter((item) => item !== key);
    updateBlock(index, { image_files: next });
  };

  $: imageKeys = Array.from(
    new Set(analysisBlocks.flatMap((block) => block.image_files ?? []).filter(Boolean))
  );

  $: if (imageKeys.join('|') !== imageKeySignature) {
    imageKeySignature = imageKeys.join('|');
    void loadImageUrls();
  }

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
        scope: 'analysis',
        block_index: index + 1
      });
      if (response?.keys?.length) {
        const existing = analysisBlocks[index]?.image_files ?? [];
        updateBlock(index, { image_files: [...existing, ...response.keys] });
      }
      input.value = '';
    } catch {
      uploadError = '画像アップロードに失敗しました。';
    } finally {
      uploadingIndex = null;
    }
  };

  const handleSave = async () => {
    if (!experiment) return;
    submitting = true;
    error = '';
    success = '';
    try {
      const items = analysisBlocks.map((block) => ({
        name: block.name || null,
        purpose: block.purpose || null,
        notes: block.notes || null,
        image_files: block.image_files
      }));
      await api.experiments.replaceAnalyses(experiment.id, { items });
      const refetch = $analysesQuery?.refetch;
      if (typeof refetch === 'function') {
        await refetch();
      }
      fromServer();
      success = '考察を保存しました。';
    } catch {
      error = '考察の保存に失敗しました。';
    } finally {
      submitting = false;
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">考察入力</h1>
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
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/evaluations`}>評価入力へ</Button.Root>
      {/if}
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">考察ブロック</h2>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" type="button" onclick={addBlock}>ブロック追加</Button.Root>
      <Button.Root class="btn-primary" type="button" onclick={handleSave} disabled={submitting}>
        保存
      </Button.Root>
    </div>
  </div>

  {#if error}
    <p class="mt-3 text-sm text-rose-600">{error}</p>
  {/if}
  {#if success}
    <p class="mt-3 text-sm text-emerald-600">{success}</p>
  {/if}
  {#if uploadError}
    <p class="mt-3 text-sm text-rose-600">{uploadError}</p>
  {/if}
  {#if imageUrlsError}
    <p class="mt-3 text-sm text-rose-600">{imageUrlsError}</p>
  {/if}

  <div class="mt-4 space-y-4">
    {#if $analysesQuery.isLoading}
      <p class="text-sm text-slate-500">読み込み中...</p>
    {:else if analysisBlocks.length}
      {#each analysisBlocks as block, index}
        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <p class="font-semibold text-slate-800">ブロック {index + 1}</p>
            <Button.Root class="btn-ghost text-xs" type="button" onclick={() => removeBlock(index)}>
              削除
            </Button.Root>
          </div>
          <div class="mt-3 grid gap-3">
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察名</span>
              <input
                class="input mt-2"
                type="text"
                value={block.name}
                on:input={(event) =>
                  updateBlock(index, { name: (event.currentTarget as HTMLInputElement).value })
                }
              />
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察目的</span>
              <input
                class="input mt-2"
                type="text"
                value={block.purpose}
                on:input={(event) =>
                  updateBlock(index, { purpose: (event.currentTarget as HTMLInputElement).value })
                }
              />
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察内容</span>
              <textarea
                class="input mt-2 min-h-[120px]"
                value={block.notes}
                on:input={(event) =>
                  updateBlock(index, { notes: (event.currentTarget as HTMLTextAreaElement).value })
                }
              ></textarea>
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">画像プレビュー</span>
              {#if block.image_files.length}
                <div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {#each block.image_files as key}
                    <div class="group relative">
                      {#if imageUrlMap[key]}
                        <img
                          src={imageUrlMap[key]}
                          alt={`考察画像 ${index + 1}`}
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
                        onclick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          handleRemoveImage(index, key);
                        }}
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
            </label>
          </div>
        </div>
      {/each}
    {:else}
      <p class="text-sm text-slate-500">考察ブロックがありません。</p>
    {/if}
  </div>
</section>
