<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import MarketSubNav from '../components/MarketSubNav.vue'
import MarketDataStatus from '../components/MarketDataStatus.vue'
import { marketApi } from '../api/stocks.js'
import { formatPct, pctClass } from '../utils/format.js'
import { formatAmount } from '../utils/marketFormat.js'

use([BarChart, TooltipComponent, GridComponent, CanvasRenderer])
const route=useRoute(),router=useRouter()
const loading=ref(false),error=ref(''),data=ref(null)
const board=ref(route.query.board==='concept'?'concept':'industry')
const q=ref(route.query.q||'')
const sort=ref(route.query.sort||'net')
const order=ref(route.query.order==='asc'?'asc':'desc')
const page=ref(Number(route.query.page)||1)
const items=computed(()=>data.value?.items||[]),summary=computed(()=>data.value?.summary||{}),pagination=computed(()=>data.value?.pagination||{page:1,total_pages:1,total:0})

function barOption(rows, side){
  if(!rows.length)return{}
  const ordered=[...rows].reverse()
  return{backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'},backgroundColor:'#101827',borderColor:'#33415f',textStyle:{color:'#ddd'},formatter(params){const p=params[0],r=ordered[p.dataIndex];return `${r.name}<br/>净额 ${formatAmount(r.net)}<br/>流入 ${formatAmount(r.inflow)}<br/>流出 ${formatAmount(r.outflow)}<br/>涨跌 ${formatPct(r.change_pct)}<br/>龙头 ${r.leader||'-'} ${formatPct(r.leader_pct)}`}},grid:{left:side==='in'?'30%':'8%',right:side==='in'?'8%':'30%',top:10,bottom:8},xAxis:{type:'value',inverse:side==='out',axisLabel:{show:false},splitLine:{show:false}},yAxis:{type:'category',position:side==='out'?'right':'left',data:ordered.map(r=>r.name),axisLabel:{color:'#a6b1c5',fontSize:11},axisLine:{show:false},axisTick:{show:false}},series:[{type:'bar',data:ordered.map(r=>Math.abs(r.net)),barWidth:9,itemStyle:{color:side==='in'?'#e36b70':'#61c297',borderRadius:4},label:{show:true,position:side==='in'?'right':'left',color:side==='in'?'#ef969a':'#8bd7b6',fontSize:10,formatter:p=>formatAmount((side==='in'?1:-1)*p.value)}}]}
}
const inflowChart=computed(()=>barOption(data.value?.inflow_top||[],'in')),outflowChart=computed(()=>barOption(data.value?.outflow_top||[],'out'))
const insight=computed(()=>{
  const s=summary.value,c=s.top_three_inflow_concentration_pct,b=s.breadth_pct
  return[
    c==null?'暂无集中度数据':`流入前三集中度 ${c.toFixed(1)}%：${c>=60?'资金集中在少数板块，追高风险较高':'资金分布相对均衡'}`,
    b==null?'暂无广度数据':`资金广度 ${b.toFixed(1)}%：${b>=50?'流入板块占多数':'流出板块占多数，注意风险偏好'}`,
    data.value?.divergences?.length?`发现 ${data.value.divergences.length} 个显著价流背离板块，需结合后续价格确认。`:'暂未发现显著价流背离。'
  ]
})
async function load(reset=false){if(reset)page.value=1;loading.value=true;error.value='';syncUrl();try{data.value=(await marketApi.getSectors({board:board.value,q:q.value||undefined,sort:sort.value,order:order.value,page:page.value,page_size:50})).data;page.value=data.value.pagination?.page||1;syncUrl()}catch(e){error.value=e.response?.data?.detail||'加载板块资金失败'}finally{loading.value=false}}
function syncUrl(){router.replace({query:{...(board.value==='concept'?{board:'concept'}:{}),...(q.value?{q:q.value}:{}),...(sort.value!=='net'?{sort:sort.value}:{}),...(order.value!=='desc'?{order:order.value}:{}),...(page.value>1?{page:page.value}:{})}})}
function switchBoard(v){board.value=v;load(true)}function changePage(d){page.value+=d;load()}
function sortBy(field){if(sort.value===field)order.value=order.value==='desc'?'asc':'desc';else{sort.value=field;order.value='desc'};load(true)}
function sortMark(field){return sort.value===field?(order.value==='desc'?'↓':'↑'):'↕'}
onMounted(load)
</script>

<template><div class="page"><MarketSubNav/>
  <div class="page-header"><div><h1>板块资金轮动</h1><p>行业 / 概念当日资金强弱与价流背离</p></div><button class="primary" @click="load()" :disabled="loading">{{loading?'加载中...':'刷新'}}</button></div>
  <div v-if="error" class="error-box">{{error}}</div>
  <div class="toolbar"><div><button :class="{active:board==='industry'}" @click="switchBoard('industry')">行业</button><button :class="{active:board==='concept'}" @click="switchBoard('concept')">概念</button></div><div class="periods"><button class="active">当日</button><button disabled>5日 · 待积累</button><button disabled>10日 · 待积累</button><button disabled>20日 · 待积累</button></div><div class="search"><input v-model.trim="q" placeholder="搜索板块或龙头" @keyup.enter="load(true)"/><button @click="load(true)">查询</button></div></div>
  <div class="summary-grid"><div><label>板块净额合计</label><b :class="pctClass(summary.net_total)">{{formatAmount(summary.net_total)}}</b></div><div><label>流入 / 流出</label><b>{{summary.inflow_count??'-'}} / {{summary.outflow_count??'-'}}</b></div><div><label>资金广度</label><b>{{formatPct(summary.breadth_pct)}}</b></div><div><label>流入前三集中度</label><b>{{formatPct(summary.top_three_inflow_concentration_pct)}}</b></div><div><label>最强流入</label><b class="up">{{summary.strongest_inflow?.name||'-'}}</b></div><div><label>最强流出</label><b class="down">{{summary.strongest_outflow?.name||'-'}}</b></div></div>
  <section class="flow-card"><div class="flow-title"><div><span>净流出较强</span><b class="down">{{formatAmount((data?.outflow_top||[]).reduce((s,r)=>s+r.net,0))}}</b></div><div class="center"><span>当日相对资金强弱</span><strong :class="pctClass(summary.net_total)">{{formatAmount(summary.net_total)}}</strong><small>横截面排名，不是板块间真实资金路径</small></div><div><span>净流入较强</span><b class="up">{{formatAmount((data?.inflow_top||[]).reduce((s,r)=>s+r.net,0))}}</b></div></div><div class="chart-row"><v-chart v-if="outflowChart.series" :option="outflowChart" autoresize/><div v-else class="chart-empty">暂无净流出数据</div><v-chart v-if="inflowChart.series" :option="inflowChart" autoresize/><div v-else class="chart-empty">暂无净流入数据</div></div></section>
  <section class="insights"><div v-for="(text,i) in insight" :key="i"><span>{{i+1}}</span><p>{{text}}</p></div></section>
  <section v-if="data?.divergences?.length" class="divergences"><h2>价流背离</h2><div><span v-for="r in data.divergences" :key="r.name">{{r.name}} <b :class="pctClass(r.net)">{{formatAmount(r.net)}}</b> / <b :class="pctClass(r.change_pct)">{{formatPct(r.change_pct)}}</b></span></div></section>
  <section class="table-card"><div class="table-title"><h2>{{board==='industry'?'行业':'概念'}}完整明细</h2><span>{{pagination.total}} 条</span></div><div class="table-wrap"><table><thead><tr><th>名称</th><th @click="sortBy('net')">净额 {{sortMark('net')}}</th><th @click="sortBy('inflow')">流入 {{sortMark('inflow')}}</th><th @click="sortBy('outflow')">流出 {{sortMark('outflow')}}</th><th @click="sortBy('change_pct')">涨跌幅 {{sortMark('change_pct')}}</th><th>公司数</th><th>领涨股</th><th @click="sortBy('leader_pct')">领涨% {{sortMark('leader_pct')}}</th></tr></thead><tbody><tr v-for="r in items" :key="r.name"><td class="name">{{r.name}}</td><td :class="pctClass(r.net)">{{formatAmount(r.net)}}</td><td>{{formatAmount(r.inflow)}}</td><td>{{formatAmount(r.outflow)}}</td><td :class="pctClass(r.change_pct)">{{formatPct(r.change_pct)}}</td><td>{{r.company_count??'-'}}</td><td>{{r.leader||'-'}}</td><td :class="pctClass(r.leader_pct)">{{formatPct(r.leader_pct)}}</td></tr></tbody></table><div v-if="!items.length&&!loading" class="empty">暂无符合条件的板块</div></div><div class="pager"><span>第 {{pagination.page}}/{{pagination.total_pages}} 页</span><div><button :disabled="pagination.page<=1" @click="changePage(-1)">上一页</button><button :disabled="pagination.page>=pagination.total_pages" @click="changePage(1)">下一页</button></div></div></section>
  <MarketDataStatus :meta="data?.meta"/>
</div></template>

<style scoped>
.page{color:#dce4f2}.page-header{display:flex;justify-content:space-between;gap:12px;margin-bottom:10px}.page-header h1{margin:0;font-size:22px}.page-header p{margin:4px 0 0;color:#71809a;font-size:13px}button{cursor:pointer;border:1px solid #293b5b;background:#111d34;color:#9eabc1;border-radius:6px;padding:7px 12px}button.active,.primary{background:#174673;color:#fff;border-color:#286391}button:disabled{opacity:.4;cursor:not-allowed}.error-box{background:#3a1520;color:#ff8796;padding:10px;border-radius:7px;margin-bottom:10px}.toolbar{display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap;margin-bottom:10px}.toolbar>div{display:flex;gap:6px}.search input{background:#0d1729;border:1px solid #293b5b;color:#ddd;border-radius:6px;padding:8px 10px}.summary-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:10px}.summary-grid>div{background:#111d34;border:1px solid #213251;border-radius:8px;padding:10px}.summary-grid label{display:block;color:#68758d;font-size:11px}.summary-grid b{display:block;margin-top:5px;font-size:15px}.flow-card{background:#0f1a2d;border:1px solid #213251;border-radius:10px;padding:12px;margin-bottom:10px}.flow-title{display:grid;grid-template-columns:1fr 1fr 1fr;align-items:center;text-align:center;color:#70809a;font-size:12px}.flow-title>div:first-child{text-align:left}.flow-title>div:last-child{text-align:right}.flow-title b{display:block;margin-top:4px}.center strong{display:block;font-size:25px;margin:5px 0}.center small{color:#56647d}.chart-row{display:grid;grid-template-columns:1fr 1fr;height:310px}.chart-row>div{height:310px}.chart-empty{display:grid;place-items:center;color:#59677e;font-size:12px}.insights{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}.insights>div{display:flex;gap:8px;align-items:flex-start;background:#111d34;border:1px solid #213251;border-radius:8px;padding:10px}.insights span{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#18365a;color:#70b9ee;font-size:11px;flex:none}.insights p{margin:2px 0;color:#9aa7ba;font-size:12px;line-height:1.5}.divergences,.table-card{background:#111d34;border:1px solid #213251;border-radius:9px;margin-bottom:10px}.divergences{padding:11px}.divergences h2,.table-title h2{font-size:14px;margin:0}.divergences>div{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.divergences span{background:#0c172a;border-radius:5px;padding:6px 8px;font-size:11px}.table-title{display:flex;justify-content:space-between;padding:10px;color:#71809a}.table-wrap{overflow:auto;max-height:540px}table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#0d192d;color:#7887a1;font-weight:500;text-align:right;padding:9px;white-space:nowrap;cursor:pointer}td{padding:8px 9px;border-bottom:1px solid #1d2a43;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}.name{color:#e0e7f1}.empty{text-align:center;color:#64718a;padding:35px}.pager{display:flex;justify-content:space-between;align-items:center;padding:9px;color:#68758d;font-size:12px}.pager button{margin-left:6px}.up{color:#e94560}.down{color:#00c853}@media(max-width:1050px){.summary-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){.summary-grid{grid-template-columns:repeat(2,1fr)}.chart-row,.insights{grid-template-columns:1fr}.chart-row{height:600px}.flow-title{grid-template-columns:1fr}.flow-title>div{text-align:center!important;margin:4px}.toolbar{display:block}.toolbar>div{margin-bottom:7px;overflow:auto}.search input{min-width:200px}}
</style>
