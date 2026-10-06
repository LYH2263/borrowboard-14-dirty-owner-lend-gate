<template>
  <div style="padding:16px">
    <h1>物主一览</h1>
    <div v-for="i in rows" :key="i.id" class="item" :class="{ 'dirty-item': i.dirty }">
      {{ i.owner || '（空）' }} · {{ i.title }} · {{ statusText(i.status) }}
      <span v-if="i.dirty" class="badge dirty">脏物·放行</span>
      <span v-else-if="i.owner_missing" class="badge warn">无主</span>
    </div>
  </div>
</template>
<script setup>
import { ref, inject, watch } from 'vue'
import { api } from '../api'
const rows = ref([])
const board = inject('board')
async function load() { rows.value = await api('/items') }
// 与看板同源刷新：借出/归还后顶细条与可借栏变动，物主栏 status 跟着同步。
watch(board, load, { deep: true })
load()
function statusText(s) {
  return s === 'available' ? '可借' : s === 'on_loan' ? '在借' : s
}
</script>
