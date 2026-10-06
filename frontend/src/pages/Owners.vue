<template>
  <div style="padding:16px">
    <h1>物主一览</h1>
    <div v-for="i in rows" :key="i.id" class="item" :class="{ blocked: i.lend_status === 'blocked' }">
      {{ i.owner || '（空）' }} · {{ i.title }}
      · 状态 <strong>{{ statusText[i.lend_status] || i.lend_status }}</strong>
      <span v-if="i.data_quality !== 'clean'" class="chip chip-block">{{ i.data_quality }}</span>
      <div v-if="i.blocked_reasons && i.blocked_reasons.length" class="muted">
        不可借原因：{{ i.blocked_reasons.map(r => reasonText[r] || r).join('、') }}
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const statusText = { lendable: '可借', on_loan: '在借', blocked: '不可借' }
const reasonText = { owner_missing: '无主', dirty_data: '脏数据' }
onMounted(async () => { rows.value = await api('/items') })
</script>
