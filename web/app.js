const state = {context: null, current: null, analysis: null, timelineBars: []};
const element = identifier => document.getElementById(identifier);

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求失败');
  return value;
}

function message(value, error = false) {
  element('status').textContent = value;
  element('status').className = error ? 'error' : '';
}

function analysisMessage(value, error = false) {
  element('analysis-status').textContent = value;
  element('analysis-status').className = error ? 'error' : '';
}

async function guarded(action) {
  try { await action(); } catch (error) { message(error.message, true); }
}

async function guardedAnalysis(action) {
  try { await action(); } catch (error) { analysisMessage(error.message, true); }
}

function selected() {
  const selection = {};
  for (const control of state.context.product.options) selection[control[0]] = element('select-' + control[0]).value;
  return {revision: element('revision').value, selection};
}

function parseGrid(text) {
  return text.split(/[,，\s]+/).filter(Boolean).map(Number).filter(value => Number.isFinite(value));
}

function currentCaliber() {
  const factors = {};
  for (const kind of ['primary', 'secondary', 'standby']) {
    const value = parseFloat(element('factor-' + kind).value);
    if (!Number.isFinite(value)) throw new Error('折算系数应为数字');
    factors[kind] = value;
  }
  const caliber = {
    factors,
    partial: element('caliber-partial').value,
    proxy: element('caliber-proxy').value,
    group_by: element('caliber-group').value
  };
  const sensitivity = {};
  const secondary = parseGrid(element('sens-secondary').value);
  const standby = parseGrid(element('sens-standby').value);
  if (secondary.length) sensitivity.secondary = secondary;
  if (standby.length) sensitivity.standby = standby;
  if (Object.keys(sensitivity).length) caliber.sensitivity = sensitivity;
  return caliber;
}

function setCaliber(caliber) {
  element('factor-primary').value = caliber.factors.primary;
  element('factor-secondary').value = caliber.factors.secondary;
  element('factor-standby').value = caliber.factors.standby;
  element('caliber-partial').value = caliber.partial;
  element('caliber-proxy').value = caliber.proxy;
  element('caliber-group').value = caliber.group_by;
  element('sens-secondary').value = (caliber.sensitivity && caliber.sensitivity.secondary || []).join(',');
  element('sens-standby').value = (caliber.sensitivity && caliber.sensitivity.standby || []).join(',');
}

function renderControls() {
  const revision = element('revision').value || state.context.default_revision;
  element('revision').replaceChildren();
  for (const dataset of state.context.datasets) {
    const option = document.createElement('option');
    option.value = dataset.revision;
    option.textContent = dataset.label + ' · ' + dataset.revision.slice(0, 9);
    element('revision').append(option);
  }
  element('revision').value = revision;
  if (!element('revision').value) element('revision').value = state.context.default_revision;
  if (!element('controls').children.length) {
    for (const [key, labelText, choices] of state.context.product.options) {
      const label = document.createElement('label');
      label.textContent = labelText;
      const select = document.createElement('select');
      select.id = 'select-' + key;
      for (const choice of choices) {
        const option = document.createElement('option');
        option.value = choice;
        option.textContent = choice;
        select.append(option);
      }
      select.value = state.context.product.selection[key];
      label.append(select);
      element('controls').append(label);
    }
    setCaliber(state.context.product.caliber);
  }
}

function displayValue(value) {
  if (value === null || value === undefined) return '未观测';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function drawChart(series) {
  const canvas = element('chart');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  const values = series.filter(point => typeof point.y === 'number' && Number.isFinite(point.y));
  context.font = '12px sans-serif';
  if (!values.length) { context.fillText('该范围没有可定量的描述值', 30, 50); return; }
  const low = Math.min(0, ...values.map(point => point.y));
  const high = Math.max(1, ...values.map(point => point.y));
  const scale = value => 250 - (value - low) / (high - low || 1) * 210;
  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(45, 20); context.lineTo(45, 250); context.lineTo(940, 250); context.stroke();
  context.fillStyle = '#0a7168';
  const scatter = values.every(point => typeof point.x === 'number');
  const minimumX = scatter ? Math.min(...values.map(point => point.x)) : 0;
  const maximumX = scatter ? Math.max(...values.map(point => point.x)) : 1;
  values.forEach((point, index) => {
    const position = scatter ? 60 + (point.x - minimumX) / (maximumX - minimumX || 1) * 850 : 55 + index * 875 / values.length;
    if (scatter) {
      context.beginPath(); context.arc(position, scale(point.y), 3.5, 0, Math.PI * 2); context.fill();
    } else {
      context.fillRect(position, Math.min(scale(point.y), scale(0)), Math.max(3, 800 / values.length), Math.max(1, Math.abs(scale(point.y) - scale(0))));
    }
    if (values.length < 12) context.fillText(point.label, position, 275);
  });
  context.fillStyle = '#29434e';
  context.fillText(high.toFixed(2), 0, 45); context.fillText(low.toFixed(2), 0, 250);
  context.fillText(scatter ? '所选资料的数值坐标（仅为原始描述）' : '按表中顺序展示描述值；缺测不绘制为零', 50, 20);
}

function render(result, heading) {
  state.current = result;
  element('summary').replaceChildren();
  for (const [label, value] of Object.entries(result.view.summary)) {
    const card = document.createElement('article');
    const title = document.createElement('span'); title.textContent = label;
    const amount = document.createElement('strong'); amount.textContent = displayValue(value);
    card.append(title, amount); element('summary').append(card);
  }
  element('notes').replaceChildren();
  for (const note of result.view.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; element('notes').append(paragraph);
  }
  const rows = result.view.rows;
  const fields = rows.length ? Object.keys(rows[0]) : [];
  const header = document.createElement('tr');
  for (const field of fields) { const cell = document.createElement('th'); cell.textContent = field; header.append(cell); }
  element('columns').replaceChildren(header); element('rows').replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr'); line.tabIndex = 0;
    for (const field of fields) { const cell = document.createElement('td'); cell.textContent = displayValue(row[field]); line.append(cell); }
    line.onclick = () => { element('details').textContent = JSON.stringify(row, null, 2); };
    line.onkeydown = event => { if (event.key === 'Enter') line.click(); };
    element('rows').append(line);
  }
  drawChart(result.view.series);
  element('details').textContent = JSON.stringify({revision: result.revision, selection: result.selection,
    history: result.view.history || null}, null, 2);
  message((heading || '已更新描述') + ' · 数据 ' + result.revision.slice(0, 12));
  const households = [...new Set(rows.map(row => row.household))].sort();
  const previous = element('household').value;
  element('household').replaceChildren();
  for (const household of households) {
    const option = document.createElement('option');
    option.value = household; option.textContent = household;
    element('household').append(option);
  }
  if (households.includes(previous)) element('household').value = previous;
  if (element('household').value) guarded(loadTimeline);
}

function fmt(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return String(Math.round(value));
}

function estimateText(block) {
  if (!block) return '—';
  return fmt(block.estimate) + '（' + fmt(block.ci[0]) + '–' + fmt(block.ci[1]) + '）';
}

function fillTable(columnsId, rowsId, headers, rows) {
  const header = document.createElement('tr');
  for (const label of headers) { const cell = document.createElement('th'); cell.textContent = label; header.append(cell); }
  element(columnsId).replaceChildren(header);
  const body = element(rowsId);
  body.replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr');
    for (const value of row) { const cell = document.createElement('td'); cell.textContent = value; line.append(cell); }
    body.append(line);
  }
}

function addCard(label, text) {
  const card = document.createElement('article');
  const title = document.createElement('span'); title.textContent = label;
  const amount = document.createElement('strong'); amount.textContent = text;
  card.append(title, amount);
  element('analysis-summary').append(card);
}

function renderAnalysis(analysis, caliber, revision) {
  state.analysis = analysis;
  const coverage = analysis.coverage;
  element('analysis-summary').replaceChildren();
  addCard('周户均钟表时间', estimateText(analysis.weekly.clock));
  addCard('周户均折算负担', estimateText(analysis.weekly.load));
  if (analysis.groups && analysis.groups.load_difference) {
    addCard('组间差·折算负担 ' + analysis.groups.load_difference.contrast, estimateText(analysis.groups.load_difference));
  }
  addCard('估计户数', coverage.households_used + '/' + coverage.households_total);
  addCard('进入估计日记', coverage.diaries_used + '/' + coverage.diaries_total);
  addCard('排除半天/代填', coverage.dropped_partial + '/' + coverage.dropped_proxy);
  const probs = ['0.1', '0.25', '0.5', '0.75', '0.9'];
  const quantileRow = (label, quantiles) => [label, ...probs.map(prob => fmt(quantiles[prob]))];
  fillTable('quantile-columns', 'quantile-rows', ['指标', 'p10', 'p25', 'p50', 'p75', 'p90'], [
    quantileRow('周户钟表时间', analysis.weekly.quantiles_clock),
    quantileRow('周户折算负担', analysis.weekly.quantiles_load)
  ]);
  const groupRows = [];
  if (analysis.groups) {
    for (const row of analysis.groups.rows) {
      groupRows.push([row.group, String(row.households), estimateText(row.clock), estimateText(row.load)]);
    }
    for (const [label, difference] of [['钟表时间差', analysis.groups.clock_difference], ['折算负担差', analysis.groups.load_difference]]) {
      if (difference) groupRows.push([difference.contrast + '（' + label + '）', '', estimateText(difference), '']);
    }
  }
  fillTable('group-columns', 'group-rows', ['组别', '户数', '钟表时间均值（95%CI）', '折算负担均值（95%CI）'],
    groupRows.length ? groupRows : [['未分组或所选范围内只有一个组', '', '', '']]);
  const sensitivity = analysis.sensitivity;
  const standbyValues = sensitivity.standby;
  const sensRows = sensitivity.secondary.map(secondary => {
    const cells = standbyValues.map(standby => {
      const cell = sensitivity.cells.find(item => item.secondary === secondary && item.standby === standby);
      return cell ? fmt(cell.mean) : '—';
    });
    return [String(secondary), ...cells];
  });
  fillTable('sens-columns', 'sens-rows', ['伴随＼待命', ...standbyValues.map(String)], sensRows);
  element('sens-notes').replaceChildren();
  const sensNote = document.createElement('p');
  const range = sensitivity.mean_range;
  const difference = sensitivity.difference_range;
  sensNote.textContent = '网格内周户均折算负担范围 ' + (range ? fmt(range[0]) + '–' + fmt(range[1]) : '—') +
    '；组间差范围 ' + (difference ? fmt(difference[0]) + '–' + fmt(difference[1]) : '—') +
    '；组间差符号' + (sensitivity.difference_sign_change ? '发生翻转，结论对折算敏感' : '未翻转') +
    '；钟表时间结果不随折算系数变化。';
  element('sens-notes').append(sensNote);
  const taskNames = [...new Set(analysis.providers.flatMap(row => Object.keys(row.tasks)))].sort();
  fillTable('provider-columns', 'provider-rows',
    ['提供者', '家庭', '区域', '周钟表时间', '周折算负担', ...taskNames.map(task => '任务：' + task)],
    analysis.providers.map(row => [row.provider, row.household, row.area, fmt(row.weekly_clock), fmt(row.weekly_load),
      ...taskNames.map(task => fmt(row.tasks[task]))]));
  fillTable('recipient-columns', 'recipient-rows',
    ['接收者', '家庭', '周接收钟表时间', '周接收人时', '双重照护分钟', '提供者'],
    analysis.recipients.map(row => [row.recipient, row.household, fmt(row.weekly_received_clock),
      fmt(row.weekly_received_person), fmt(row.weekly_double_coverage), row.providers.join('、')]));
  fillTable('diary-columns', 'diary-rows',
    ['日记', '提供者', '日期类型', '代填', '覆盖分钟', '钟表时间', '填报分钟', '折算负担', '并行分钟', '最大并行',
     '多接收者分钟', '跨午夜分钟', '窗口前记录', '进入周估计'],
    analysis.diaries.map(row => [row.diary, row.provider, row.day_type, row.proxy ? '是' : '否',
      fmt(row.coverage_minutes), fmt(row.clock_minutes), fmt(row.reported_minutes), fmt(row.load_minutes),
      fmt(row.concurrent_minutes), fmt(row.max_concurrency), fmt(row.multi_recipient_minutes),
      fmt(row.cross_midnight_minutes), fmt(row.before_window_minutes),
      row.used_in_weekly ? '是' : '否' + (row.drop_reason ? '（' + row.drop_reason + '）' : '')]));
  element('analysis-notes').replaceChildren();
  for (const note of analysis.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; element('analysis-notes').append(paragraph);
  }
  const factors = caliber.factors;
  analysisMessage('研究估计已更新 · 口径 主' + factors.primary + '/伴' + factors.secondary + '/待' + factors.standby +
    ' · 半天:' + caliber.partial + ' · 代填:' + caliber.proxy + ' · 数据 ' + revision.slice(0, 12));
}

async function runAnalysis() {
  const payload = {...selected(), caliber: currentCaliber()};
  const response = await request('/api/analyze', payload);
  renderAnalysis(response.analysis, response.caliber, response.revision);
}

const KIND_COLORS = {primary: '#0a7168', secondary: '#d97925', standby: '#9db8c0'};
const TASK_MARKS = {meal: '餐', supervision: '陪', waiting: '待', clean: '洁'};
const RECEIVED_COLORS = ['#bfe3da', '#4a9b8e', '#2e7d6b'];

function drawTimeline(timeline) {
  const canvas = element('timeline');
  const context = canvas.getContext('2d');
  const rows = [];
  const design = timeline.design || {workday_factor: 5, weekend_factor: 2};
  const dayFactor = {weekday: design.workday_factor, weekend: design.weekend_factor};
  const dayName = {weekday: '工作日', weekend: '周末'};
  let maxStop = 1560;
  for (const day of timeline.days) {
    rows.push({type: 'day', day});
    for (const diary of day.diaries) {
      rows.push({type: 'provider', diary});
      for (const activity of diary.activities) maxStop = Math.max(maxStop, activity.stop);
    }
    for (const recipient of day.recipients) {
      rows.push({type: 'recipient', recipient});
      for (const segment of recipient.segments) maxStop = Math.max(maxStop, segment[1]);
    }
  }
  maxStop = Math.ceil(maxStop / 60) * 60;
  const left = 170, right = 16, top = 26, bottom = 30, rowHeight = 30, labelHeight = 24;
  let height = top + bottom;
  for (const row of rows) height += row.type === 'day' ? labelHeight : rowHeight;
  canvas.height = height;
  const x = value => left + value / maxStop * (canvas.width - left - right);
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.font = '12px sans-serif';
  state.timelineBars = [];
  canvas._bars = state.timelineBars;
  let y = top;
  for (const row of rows) {
    if (row.type === 'day') {
      context.fillStyle = '#29434e';
      context.fillText(dayName[row.day.day_type] + '（周因子×' + dayFactor[row.day.day_type] + '）', 8, y + 16);
      y += labelHeight;
      continue;
    }
    const middle = y + rowHeight / 2 + 4;
    if (row.type === 'provider') {
      const diary = row.diary;
      context.fillStyle = '#4c6570';
      context.fillText(diary.provider + (diary.proxy ? '（代填）' : ''), 8, middle);
      context.fillStyle = 'rgba(90,110,115,0.18)';
      context.fillRect(x(0), y + 4, x(diary.observed_start) - x(0), rowHeight - 8);
      context.fillRect(x(diary.observed_stop), y + 4, x(maxStop) - x(diary.observed_stop), rowHeight - 8);
      for (const activity of diary.activities) {
        const x0 = x(activity.start), x1 = x(activity.stop);
        context.fillStyle = KIND_COLORS[activity.kind] || '#666';
        context.fillRect(x0, y + 5, Math.max(2, x1 - x0), rowHeight - 10);
        context.strokeStyle = 'rgba(20,40,45,0.35)';
        context.strokeRect(x0, y + 5, Math.max(2, x1 - x0), rowHeight - 10);
        if (x1 - x0 > 18) {
          context.fillStyle = '#fff';
          context.fillText(TASK_MARKS[activity.task] || activity.task.slice(0, 1), x0 + 4, middle);
        }
        state.timelineBars.push({x0, x1, y0: y + 5, y1: y + rowHeight - 5,
          record: {类型: '活动', 日记: diary.diary, 提供者: diary.provider, ...activity}});
      }
    } else {
      const recipient = row.recipient;
      context.fillStyle = '#4c6570';
      context.fillText('接收端 ' + recipient.recipient, 8, middle);
      for (const segment of recipient.segments) {
        const x0 = x(segment[0]), x1 = x(segment[1]);
        context.fillStyle = RECEIVED_COLORS[Math.min(segment[2], 3) - 1];
        context.fillRect(x0, y + 7, Math.max(2, x1 - x0), rowHeight - 14);
        state.timelineBars.push({x0, x1, y0: y + 7, y1: y + rowHeight - 7,
          record: {类型: '接收段', 接收者: recipient.recipient, start: segment[0], stop: segment[1], 同时提供者数: segment[2]}});
      }
    }
    y += rowHeight;
  }
  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(left, 12); context.lineTo(left, y); context.stroke();
  context.fillStyle = '#29434e';
  for (let tick = 0; tick <= maxStop; tick += 240) {
    const position = x(tick);
    context.beginPath(); context.moveTo(position, y); context.lineTo(position, y + 5); context.stroke();
    context.fillText(Math.floor(tick / 60) + ':00', position - 12, y + 18);
  }
  if (maxStop > 1440) {
    const midnight = x(1440);
    context.strokeStyle = '#9c302d';
    context.setLineDash([4, 4]);
    context.beginPath(); context.moveTo(midnight, 10); context.lineTo(midnight, y); context.stroke();
    context.setLineDash([]);
    context.fillStyle = '#9c302d';
    context.fillText('次日0:00', midnight + 4, 20);
  }
  const partialCount = timeline.days.reduce((total, day) =>
    total + day.diaries.filter(diary => diary.observed_stop - diary.observed_start < 1440).length, 0);
  element('timeline-details').textContent = JSON.stringify({
    家庭: timeline.household, 设计: design,
    日记: timeline.days.flatMap(day => day.diaries.map(diary => ({
      日记: diary.diary, 提供者: diary.provider, 代填: diary.proxy,
      覆盖: [diary.observed_start, diary.observed_stop],
      钟表时间: diary.measures.clock_minutes, 跨午夜: diary.measures.cross_midnight_minutes,
      窗口前记录: diary.measures.before_window_minutes
    }))),
    提示: partialCount ? '灰色为未观测时段（不视为休息）；虚线为次日0:00。' : '虚线为次日0:00。'
  }, null, 2);
}

async function loadTimeline() {
  const household = element('household').value;
  if (!household) return;
  const revision = element('revision').value || state.context.default_revision;
  const response = await request('/api/household?revision=' + encodeURIComponent(revision) +
    '&household=' + encodeURIComponent(household));
  drawTimeline(response.timeline);
}

async function refresh() {
  state.context = await request('/api/context');
  renderControls();
  element('archive').replaceChildren();
  for (const notebook of state.context.notebooks) {
    const button = document.createElement('button'); button.textContent = notebook.title + ' #' + notebook.id;
    button.onclick = () => guarded(async () => {
      const saved = await request('/api/notebooks/' + notebook.id);
      element('revision').value = saved.revision;
      for (const [key, value] of Object.entries(saved.selection)) {
        const control = element('select-' + key); if (control) control.value = value;
      }
      render(saved.result, '已读取保存的描述，不随新数据变化');
      if (saved.result.caliber) setCaliber(saved.result.caliber);
      if (saved.result.analysis) {
        renderAnalysis(saved.result.analysis, saved.result.caliber, saved.revision);
      } else {
        state.analysis = null;
        element('analysis-summary').replaceChildren();
        analysisMessage('该记录保存时不含研究估计；可按当前口径重新运行。');
      }
    });
    element('archive').append(button);
  }
}

element('inspect').onclick = () => guarded(async () => {
  render(await request('/api/explore', selected()));
  await guardedAnalysis(runAnalysis);
});
element('analyze').onclick = () => guardedAnalysis(runAnalysis);
element('caliber-reset').onclick = () => guardedAnalysis(async () => {
  setCaliber(state.context.product.caliber);
  await runAnalysis();
});
element('household').onchange = () => guarded(loadTimeline);
element('timeline').onclick = event => {
  const canvas = element('timeline');
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * canvas.width / rect.width;
  const y = (event.clientY - rect.top) * canvas.height / rect.height;
  const bar = state.timelineBars.find(item => x >= item.x0 && x <= item.x1 && y >= item.y0 && y <= item.y1);
  if (bar) element('timeline-details').textContent = JSON.stringify(bar.record, null, 2);
};
element('save').onclick = () => guarded(async () => {
  const saved = await request('/api/notebooks', {...selected(), title: element('title').value, caliber: currentCaliber()});
  await refresh();
  render(saved.result, '已保存记录 #' + saved.id);
  if (saved.result.analysis) renderAnalysis(saved.result.analysis, saved.result.caliber, saved.revision);
});
element('raw').onclick = () => guarded(async () => {
  const revision = state.current ? state.current.revision : element('revision').value;
  element('details').textContent = JSON.stringify(await request('/api/data?revision=' + encodeURIComponent(revision)), null, 2);
});
element('upload').onchange = () => guarded(async () => {
  const file = element('upload').files[0]; if (!file) return;
  const data = JSON.parse(await file.text());
  const uploaded = await request('/api/datasets', {label: file.name, data});
  await refresh(); element('revision').value = uploaded.revision;
  render(await request('/api/explore', selected()), '已导入独立数据版本');
  await guardedAnalysis(runAnalysis);
});
element('export').onclick = () => guarded(async () => {
  if (!state.current) throw new Error('请先查看一个范围');
  const data = await request('/api/data?revision=' + encodeURIComponent(state.current.revision));
  const blob = new Blob([JSON.stringify({description: state.current, analysis: state.analysis, data}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'analysis-' + state.current.revision.slice(0, 12) + '.json'; link.click();
  URL.revokeObjectURL(url);
});
guarded(async () => {
  await refresh();
  render(await request('/api/explore', selected()));
  await guardedAnalysis(runAnalysis);
});
