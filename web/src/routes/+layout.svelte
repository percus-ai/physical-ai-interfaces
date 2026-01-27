<script lang="ts">
  import '../app.css';
  import AppShell from '$lib/components/AppShell.svelte';
  import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: false
      }
    }
  });
</script>

<QueryClientProvider client={queryClient}>
  <AppShell>
    <slot />
  </AppShell>
</QueryClientProvider>
