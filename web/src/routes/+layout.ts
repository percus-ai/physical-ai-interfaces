import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';

import { api } from '$lib/api/client';

export const ssr = false;

export const load: LayoutLoad = async ({ url }) => {
  if (url.pathname.startsWith('/auth')) {
    return {};
  }
  try {
    const status = await api.auth.status();
    const now = Math.floor(Date.now() / 1000);
    let authenticated = Boolean(status.authenticated);
    let expiresAt = status.expires_at;
    let sessionExpiresAt = status.session_expires_at;
    const refreshLeewaySeconds = 60;

    if (!authenticated && sessionExpiresAt && sessionExpiresAt > now) {
      try {
        const refreshed = await api.auth.refresh();
        authenticated = Boolean(refreshed.authenticated);
        expiresAt = refreshed.expires_at;
        sessionExpiresAt = refreshed.session_expires_at;
      } catch {
        authenticated = false;
      }
    }

    if (authenticated && expiresAt && expiresAt <= now + refreshLeewaySeconds) {
      try {
        await api.auth.refresh();
      } catch {
        authenticated = false;
      }
    }

    if (!authenticated) {
      throw new Error('unauthenticated');
    }
  } catch {
    throw redirect(302, '/auth');
  }
  return {};
};
