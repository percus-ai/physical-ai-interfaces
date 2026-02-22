<script lang="ts">
  import { Combobox } from 'bits-ui';

  export type BlueprintComboboxItem = {
    id: string;
    name: string;
  };

  let {
    items,
    value = '',
    disabled = false,
    placeholder = 'ブループリントを検索',
    emptyMessage = '一致するブループリントがありません。',
    onSelect
  }: {
    items: BlueprintComboboxItem[];
    value?: string;
    disabled?: boolean;
    placeholder?: string;
    emptyMessage?: string;
    onSelect?: (blueprintId: string) => void | Promise<void>;
  } = $props();

  let open = $state(false);
  let query = $state('');

  const selectedLabel = $derived(items.find((item) => item.id === value)?.name ?? '');
  const displayInputValue = $derived(query || selectedLabel);
  const normalizedQuery = $derived(query.trim().toLowerCase());
  const filteredItems = $derived.by(() => {
    if (!normalizedQuery) return items;
    return items.filter((item) => item.name.toLowerCase().includes(normalizedQuery));
  });
  const lookupItems = $derived.by(() =>
    items.map((item) => ({ value: item.id, label: item.name }))
  );

  const handleInput = (event: Event) => {
    query = (event.currentTarget as HTMLInputElement).value;
  };

  const handleValueChange = (nextValue: string) => {
    query = '';
    if (!nextValue) return;
    void onSelect?.(nextValue);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    open = nextOpen;
    if (!nextOpen) {
      query = '';
    }
  };

  $effect(() => {
    value;
    query = '';
  });
</script>

<Combobox.Root
  type="single"
  value={value}
  inputValue={displayInputValue}
  onValueChange={handleValueChange}
  items={lookupItems}
  open={open}
  onOpenChange={handleOpenChange}
  {disabled}
>
  <div class="relative">
    <Combobox.Input
      class="input pr-10"
      {disabled}
      {placeholder}
      autocomplete="off"
      oninput={handleInput}
    />
    <Combobox.Trigger
      class="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100"
      {disabled}
      aria-label="ブループリント一覧を開く"
    >
      ▾
    </Combobox.Trigger>
  </div>

  <Combobox.Portal>
    <Combobox.Content
      sideOffset={8}
      class="z-50 w-[var(--bits-combobox-anchor-width)] rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
    >
      <Combobox.Viewport class="max-h-64 overflow-y-auto">
        {#if filteredItems.length === 0}
          <div class="px-3 py-2 text-xs text-slate-500">{emptyMessage}</div>
        {:else}
          {#each filteredItems as item (item.id)}
            <Combobox.Item value={item.id} label={item.name}>
              {#snippet children({ selected, highlighted })}
                <div
                  class={`flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                    highlighted ? 'bg-slate-100 text-slate-900' : 'text-slate-700'
                  }`}
                >
                  <span class="truncate">{item.name}</span>
                  {#if selected}
                    <span class="text-xs font-semibold text-brand">選択中</span>
                  {/if}
                </div>
              {/snippet}
            </Combobox.Item>
          {/each}
        {/if}
      </Combobox.Viewport>
    </Combobox.Content>
  </Combobox.Portal>
</Combobox.Root>
