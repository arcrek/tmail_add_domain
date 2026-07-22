<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../api'
import type { AdminSettings, AdminSiteSettings } from '../types'

const props = defineProps<{ site: AdminSiteSettings; csrf: string }>()
const emit = defineEmits<{ updated: [settings: AdminSettings]; busy: [value: boolean] }>()

function generalValues(site: AdminSiteSettings) {
  return {
    appName: site.appName,
    logoDataUrl: site.logoDataUrl,
    faviconDataUrl: site.faviconDataUrl,
    primaryColor: site.primaryColor,
    accentColor: site.accentColor,
    language: site.language,
    cookieEnabled: site.cookieEnabled,
    cookieText: site.cookieText,
  }
}

const draft = reactive(generalValues(props.site))
const pending = ref(false)
const filePending = ref(0)
const status = ref('')
const error = ref('')
const fileVersions = { logoDataUrl: 0, faviconDataUrl: 0 }

watch([pending, filePending], ([saving, files]) => emit('busy', saving || files > 0))

watch(() => props.site, (value) => {
  if (!pending.value && filePending.value === 0) Object.assign(draft, generalValues(value))
})

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Could not read image.'))
    reader.onerror = () => reject(new Error('Could not read image.'))
    reader.onabort = () => reject(new Error('Could not read image.'))
    reader.readAsDataURL(file)
  })
}

async function chooseImage(event: Event, key: 'logoDataUrl' | 'faviconDataUrl'): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const version = ++fileVersions[key]
  error.value = ''
  if (!file.type.startsWith('image/')) {
    error.value = 'Choose an image file.'
    return
  }
  if (file.size > 1024 * 1024) {
    error.value = 'Images must be no larger than 1 MiB.'
    return
  }
  filePending.value += 1
  try {
    const value = await readFile(file)
    if (version === fileVersions[key]) draft[key] = value
  } catch (cause) {
    if (version === fileVersions[key]) error.value = cause instanceof Error ? cause.message : 'Could not read image.'
  } finally {
    filePending.value -= 1
  }
}

async function save(): Promise<void> {
  pending.value = true
  error.value = ''
  status.value = ''
  try {
    const settings = await api.admin.updateSettings({ site: { ...draft } }, props.csrf)
    emit('updated', settings)
    status.value = 'General settings saved.'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save general settings.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="admin-section" aria-labelledby="general-title">
    <p class="eyebrow">Appearance and language</p>
    <h1 id="general-title">General</h1>
    <form class="settings-form" @submit.prevent="save">
      <fieldset class="settings-fields" :disabled="pending || filePending > 0">
        <div class="settings-grid">
          <div class="field"><label for="app-name">App name</label><input id="app-name" v-model.trim="draft.appName" name="appName" required></div>
          <div class="field"><label for="language">Language</label><input id="language" v-model.trim="draft.language" name="language" required></div>
          <div class="field"><label for="primary-color">Primary color</label><input id="primary-color" v-model="draft.primaryColor" name="primaryColor" type="color"></div>
          <div class="field"><label for="accent-color">Accent color</label><input id="accent-color" v-model="draft.accentColor" name="accentColor" type="color"></div>
          <div class="field"><label for="logo">Logo image</label><input id="logo" name="logo" type="file" accept="image/*" @change="chooseImage($event, 'logoDataUrl')"><small>Image, 1 MiB maximum.</small></div>
          <div class="field"><label for="favicon">Favicon image</label><input id="favicon" name="favicon" type="file" accept="image/*" @change="chooseImage($event, 'faviconDataUrl')"><small>Image, 1 MiB maximum.</small></div>
        </div>
        <label class="check-field"><input v-model="draft.cookieEnabled" name="cookieEnabled" type="checkbox"> Show cookie notice</label>
        <div class="field"><label for="cookie-text">Cookie notice text</label><textarea id="cookie-text" v-model="draft.cookieText" name="cookieText" rows="4" :disabled="!draft.cookieEnabled" /></div>
        <div class="form-actions"><button class="primary-button" type="submit" :disabled="pending || filePending > 0">{{ pending ? 'Saving' : 'Save general settings' }}</button></div>
      </fieldset>
      <p class="form-status" aria-live="polite">{{ status }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>
