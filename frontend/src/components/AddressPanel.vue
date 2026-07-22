<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, api } from '../api'
import { loadSessions, removeSession } from '../session'
import type { AddressSession, DomainResource } from '../types'

defineProps<{ initialError?: string }>()
const emit = defineEmits<{ open: [session: AddressSession] }>()

const domains = ref<DomainResource[]>([])
const selectedDomain = ref('')
const localPart = ref('')
const loadingDomains = ref(true)
const submitting = ref(false)
const error = ref('')
const domainError = ref('')
const copied = ref(false)
const sessions = ref(loadSessions())

const address = computed(() =>
  localPart.value && selectedDomain.value
    ? `${localPart.value.trim().toLowerCase()}@${selectedDomain.value}`
    : '',
)

watch(address, () => { copied.value = false })

const message = (value: unknown) =>
  value instanceof ApiError ? value.message : 'The mail service is unavailable. Try again.'

async function loadDomains(): Promise<void> {
  loadingDomains.value = true
  domainError.value = ''
  try {
    const response = await api.domains()
    domains.value = response['hydra:member'].filter((domain) => domain.isActive !== false)
    selectedDomain.value = domains.value[0]?.domain ?? ''
  } catch (cause) {
    domainError.value = message(cause)
  } finally {
    loadingDomains.value = false
  }
}

onMounted(loadDomains)

async function submit(): Promise<void> {
  if (!address.value) return
  submitting.value = true
  error.value = ''
  try {
    const response = await api.token(address.value)
    emit('open', { address: address.value, token: response.token })
  } catch (cause) {
    error.value = message(cause)
  } finally {
    submitting.value = false
  }
}

function randomize(): void {
  const consonants = 'bcdfghjkmnprstvwxz'
  const vowels = 'aeiou'
  const values = crypto.getRandomValues(new Uint32Array(6))
  localPart.value = Array.from(values, (value, index) => {
    const alphabet = index % 2 ? vowels : consonants
    return alphabet[value % alphabet.length]!
  }).join('')
}

async function copyAddress(): Promise<void> {
  if (!address.value) return
  try {
    await navigator.clipboard.writeText(address.value)
    copied.value = true
  } catch {
    error.value = 'Copy failed. Select the address and copy it manually.'
  }
}

function forget(address: string): void {
  sessions.value = removeSession(address)
}
</script>

<template>
  <section class="address-layout" aria-labelledby="address-title">
    <div class="address-intro">
      <p class="eyebrow">Temporary inbox</p>
      <h1 id="address-title">Receive mail. Keep your address.</h1>
      <p class="lede">Choose a name, open the inbox, and leave no account behind.</p>
    </div>

    <div class="address-workspace">
      <div v-if="loadingDomains" class="panel loading-panel" aria-live="polite">
        <span class="skeleton skeleton-label" />
        <span class="skeleton skeleton-field" />
        <span class="skeleton skeleton-button" />
        <span class="sr-only">Loading receiving domains</span>
      </div>

      <div v-else-if="domainError" class="panel empty-state" role="alert">
        <h2>Domains could not be loaded</h2>
        <p>{{ domainError }}</p>
        <button type="button" @click="loadDomains">Retry</button>
      </div>

      <div v-else-if="domains.length === 0" class="panel empty-state">
        <h2>No receiving domains are available</h2>
        <p>Try again later or ask the site administrator to enable a domain.</p>
        <button type="submit" disabled>Open inbox</button>
      </div>

      <form v-else class="panel address-form" @submit.prevent="submit">
        <div class="panel-heading">
          <h2>Create an address</h2>
          <button class="text-button" type="button" @click="randomize">Random name</button>
        </div>

        <div class="address-fields">
          <div class="field local-field">
            <label for="local-part">Address name</label>
            <input
              id="local-part"
              v-model="localPart"
              name="local-part"
              autocomplete="off"
              autocapitalize="none"
              minlength="1"
              maxlength="64"
              pattern="[A-Za-z0-9](?:[A-Za-z0-9._+\-]*[A-Za-z0-9])?"
              required
            >
          </div>
          <span class="at-sign" aria-hidden="true">@</span>
          <div class="field domain-field">
            <label for="domain">Receiving domain</label>
            <select id="domain" v-model="selectedDomain" name="domain" required>
              <option v-for="domain in domains" :key="domain.id" :value="domain.domain">
                {{ domain.domain }}
              </option>
            </select>
          </div>
        </div>

        <div class="address-preview">
          <span>{{ address || 'Your address appears here' }}</span>
          <button class="text-button" type="button" :disabled="!address" @click="copyAddress">
            {{ copied ? 'Copied' : 'Copy' }}
          </button>
        </div>

        <p class="form-error" aria-live="polite">{{ error || initialError }}</p>
        <button class="primary-button" type="submit" :disabled="submitting || !address">
          {{ submitting ? 'Opening inbox' : 'Open inbox' }}
        </button>
      </form>

      <section v-if="sessions.length" class="remembered" aria-labelledby="remembered-title">
        <h2 id="remembered-title">Remembered inboxes</h2>
        <ul>
          <li v-for="session in sessions" :key="session.address">
            <button class="saved-address" type="button" @click="emit('open', session)">
              {{ session.address }}
            </button>
            <button class="forget-button" type="button" :aria-label="`Forget ${session.address}`" @click="forget(session.address)">
              Forget
            </button>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>
