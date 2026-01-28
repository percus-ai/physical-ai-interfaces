<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { navItems, quickActions } from '$lib/navigation';
  import { Button } from 'bits-ui';

  import { api } from '$lib/api/client';

  let mobileOpen = false;
  let authenticated = false;
  let lastPath = '';

  const authItems = {
    login: {
      id: 'login',
      label: 'ログイン',
      href: '/auth?mode=login',
      icon: '🔐',
      description: 'サインイン'
    },
    logout: {
      id: 'logout',
      label: 'ログアウト',
      href: '/auth?mode=logout',
      icon: '🚪',
      description: 'セッションを終了'
    }
  };

  const closeMobile = () => {
    mobileOpen = false;
  };

  const refreshAuth = async () => {
    try {
      const status = await api.auth.status();
      authenticated = Boolean(status.authenticated);
    } catch {
      authenticated = false;
    }
  };

  $: {
    const currentPath = $page.url.pathname + $page.url.search;
    if (currentPath !== lastPath) {
      lastPath = currentPath;
      refreshAuth();
    }
  }

  onMount(refreshAuth);
</script>

<div class="min-h-screen">
  <header class="sticky top-0 z-30 w-full border-b border-white/60 bg-white/70 backdrop-blur h-[var(--app-header-height)]">
    <div class="mx-auto flex h-full max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
      <div class="flex items-center gap-3">
        <button
          class="flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-lg shadow-sm lg:hidden"
          on:click={() => (mobileOpen = !mobileOpen)}
          aria-label="メニューを開く"
        >
          ☰
        </button>
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">Daihen Physical AI</p>
          <p class="text-lg font-semibold text-slate-900">Phi Web Console</p>
        </div>
      </div>
      <div class="hidden items-center gap-2 lg:flex">
        {#each quickActions as action}
          <Button.Root
            class={action.tone === 'primary' ? 'btn-primary' : 'btn-ghost'}
            href={action.href}
          >
            {action.label}
          </Button.Root>
        {/each}
        <Button.Root class="btn-ghost" href="/config">設定</Button.Root>
      </div>
    </div>
  </header>

  <div class="mx-auto grid max-w-7xl gap-6 px-4 py-[var(--app-shell-gap)] sm:px-6 lg:grid-cols-[240px_1fr]">
    <aside
      class={`glass fixed inset-0 z-40 h-full w-full max-w-[280px] overflow-y-auto border-r border-white/70 bg-white/90 p-6 transition lg:sticky lg:inset-auto lg:top-[calc(var(--app-header-height)+var(--app-shell-gap))] lg:h-[var(--app-shell-height)] lg:w-auto lg:max-w-none lg:translate-x-0 ${
        mobileOpen ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div class="flex h-full flex-col">
        <div class="mb-6 flex items-center justify-between lg:hidden">
          <p class="text-sm font-semibold text-slate-600">メニュー</p>
          <button
            class="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm"
            on:click={closeMobile}
          >
            閉じる
          </button>
        </div>
        <nav class="space-y-2">
          {#each navItems as item}
            <a
              href={item.href}
              class={`group flex items-start gap-3 rounded-2xl border border-transparent px-3 py-2 transition hover:border-slate-200 hover:bg-white ${
                $page.url.pathname === item.href
                  ? 'border-slate-200 bg-white shadow-sm'
                  : 'text-slate-600'
              }`}
              on:click={closeMobile}
            >
              <span class="text-lg">{item.icon}</span>
              <span>
                <span class="block text-sm font-semibold text-slate-900">{item.label}</span>
                <span class="block text-xs text-slate-500">{item.description}</span>
              </span>
            </a>
          {/each}
        </nav>

        <div class="flex-1"></div>
        <div class="mb-4 h-px w-full bg-slate-200/70"></div>
        <nav class="space-y-2">
          {#each authenticated ? [authItems.logout] : [authItems.login] as item}
            <a
              href={item.href}
              class={`group flex items-start gap-3 rounded-2xl border border-transparent px-3 py-2 transition hover:border-slate-200 hover:bg-white ${
                $page.url.pathname === '/auth' ? 'text-slate-700' : 'text-slate-600'
              }`}
              on:click={closeMobile}
            >
              <span class="text-lg">{item.icon}</span>
              <span>
                <span class="block text-sm font-semibold text-slate-900">{item.label}</span>
                <span class="block text-xs text-slate-500">{item.description}</span>
              </span>
            </a>
          {/each}
        </nav>
      </div>
    </aside>

    <main class="space-y-8">
      <slot />
    </main>
  </div>

  {#if mobileOpen}
    <button
      class="fixed inset-0 z-30 bg-slate-900/20 lg:hidden"
      on:click={closeMobile}
      aria-label="メニューを閉じる"
    ></button>
  {/if}
</div>
