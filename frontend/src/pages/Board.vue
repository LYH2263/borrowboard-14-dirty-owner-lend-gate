<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="o in outcomes" :key="o.id" class="outcome" :class="{ ok: o.ok, fail: !o.ok }">
        <strong>{{ o.title }}</strong>：{{
          o.ok
            ? ('本次扣到 ✓ 借据 #' + o.loan_id + (o.dirty ? '（仍是脏物·无主，未洗数据）' : ''))
            : ('本次没扣到 · ' + o.detail)
        }}
      </div>
      <div v-for="i in board.available" :key="i.id" class="item" :class="{ 'dirty-item': i.dirty }">
        <strong>{{ i.title }}</strong>
        <span v-if="i.dirty" class="badge dirty" title="数据质量为脏且无主，政策放行：可借但不洗数据">脏物·放行</span>
        <span v-else-if="i.owner_missing" class="badge warn">无主</span>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <button @click="lend(i)">借出通过</button>
      </div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <button @click="ret(l.id)">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const forms = reactive({})
const outcomes = reactive({})   // itemId -> 最近一次"扣到/没扣到"
watch(board, (b) => {
  for (const i of (b.available || [])) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31' }
  }
}, { immediate: true, deep: true })
async function lend(i) {
  try {
    const r = await api('/items/' + i.id + '/lend', { method: 'POST', body: JSON.stringify(forms[i.id]) })
    outcomes[i.id] = { id: i.id, title: i.title, ok: true, loan_id: r.loan_id, dirty: r.dirty }
  } catch (e) {
    // 409 等：本次没扣到，物品原样留在可借栏（后端不洗数据、不补 owner）
    outcomes[i.id] = { id: i.id, title: i.title, ok: false, detail: e.message }
  }
  await reload()
}
async function ret(id) {
  await api('/loans/' + id + '/return', { method: 'POST', body: '{}' })
  await reload()
}
</script>
