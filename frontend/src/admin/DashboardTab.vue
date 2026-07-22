<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { DashboardResource } from '../types'

const dashboard = ref<DashboardResource | null>(null)
const loading = ref(false)
const error = ref('')

function dateTime(value?: string): string {
  return value ? new Date(value).toLocaleString() : 'Not yet'
}

function syncText(value: DashboardResource['lastSync'], empty: string): string {
  if (!value.created_at) return empty
  return `${value.detail || 'No detail'}, ${dateTime(value.created_at)}`
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    dashboard.value = await api.admin.dashboard()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not load mail activity.'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section class="admin-section" aria-labelledby="dashboard-title">
    <div class="admin-section-heading">
      <div>
        <p class="eyebrow">Mail activity</p>
        <h1 id="dashboard-title">Dashboard</h1>
      </div>
      <button class="secondary-button compact-button" type="button" :disabled="loading" @click="refresh">
        {{ loading ? 'Refreshing' : 'Refresh' }}
      </button>
    </div>

    <div v-if="loading && !dashboard" class="metric-grid" aria-live="polite">
      <span v-for="index in 6" :key="index" class="skeleton metric-skeleton" />
      <span class="sr-only">Loading mail activity</span>
    </div>

    <template v-else-if="dashboard">
      <dl class="metric-grid">
        <div><dt>Active domains</dt><dd>{{ dashboard.domains.active }}</dd></div>
        <div><dt>Stored messages</dt><dd>{{ dashboard.messages.stored }}</dd></div>
        <div><dt>Messages today</dt><dd>{{ dashboard.messages.today }}</dd></div>
        <div><dt>Messages in seven days</dt><dd>{{ dashboard.messages.sevenDays }}</dd></div>
        <div><dt>Provisions today</dt><dd>{{ dashboard.domains.domainsToday }}</dd></div>
        <div><dt>Provisions in seven days</dt><dd>{{ dashboard.domains.domainsSevenDays }}</dd></div>
      </dl>

      <div class="admin-data-grid">
        <section aria-labelledby="recent-domains-title">
          <h2 id="recent-domains-title">Recent provisioned domains</h2>
          <div class="table-scroll">
            <table>
              <thead><tr><th scope="col">Domain</th><th scope="col">Provisioned</th></tr></thead>
              <tbody>
                <tr v-for="item in dashboard.domains.recentDomains" :key="`${item.domain}-${item.created_at}`">
                  <td>{{ item.domain }}</td><td><time :datetime="item.created_at">{{ dateTime(item.created_at) }}</time></td>
                </tr>
                <tr v-if="!dashboard.domains.recentDomains.length"><td colspan="2">No domains provisioned yet.</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="sync-summary" aria-labelledby="sync-summary-title">
          <h2 id="sync-summary-title">Domain sync</h2>
          <dl>
            <div><dt>Auto-sync</dt><dd>{{ dashboard.autoSyncDomains ? 'On' : 'Off' }}</dd></div>
            <div><dt>Last successful sync</dt><dd>{{ syncText(dashboard.lastSuccessfulSync, 'Not yet') }}</dd></div>
            <div><dt>Last error</dt><dd :class="{ 'status-error': dashboard.lastSyncError.created_at }">{{ syncText(dashboard.lastSyncError, 'None') }}</dd></div>
          </dl>
        </section>
      </div>
    </template>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>
