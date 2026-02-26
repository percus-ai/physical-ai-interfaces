import { browser } from '$app/environment';

const STORAGE_KEY = 'PERCUS_BACKEND_URL';
const DEFAULT_URL = 'http://localhost:8000';

export function getBackendUrl(): string {
  if (!browser) return DEFAULT_URL;
  return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_URL;
}

export function setBackendUrl(url: string): void {
  if (!browser) return;
  localStorage.setItem(STORAGE_KEY, url);
}

export function clearBackendUrl(): void {
  if (!browser) return;
  localStorage.removeItem(STORAGE_KEY);
}
