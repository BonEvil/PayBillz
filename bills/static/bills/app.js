'use strict';
// Progressive enhancement: regular links and native selects work without JavaScript.
const kind = document.getElementById('id_kind');
if (kind) {
  const update = () => document.querySelectorAll('[data-for]').forEach(el => { el.hidden = !el.dataset.for.split(' ').includes(kind.value); });
  kind.addEventListener('change', update); update();
}
const addCategory = document.getElementById('id_add_category');
if (addCategory) {
  const update = () => {
    document.querySelectorAll('[data-new-category]').forEach(el => { el.hidden = !addCategory.checked; });
    document.getElementById('id_category').disabled = addCategory.checked;
  };
  addCategory.addEventListener('change', update); update();
}
const picker = document.getElementById('icon-picker');
if (picker && typeof picker.showModal === 'function') {
  const categories = JSON.parse(document.getElementById('category-icons').textContent);
  const category = document.getElementById('id_category');
  const search = document.getElementById('icon-search');
  const choices = [...picker.querySelectorAll('[data-icon-search]')];
  const group = document.getElementById('icon-group');
  const filterIcons = () => {
    const terms = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    choices.forEach(choice => {
      choice.hidden = (group.value && choice.dataset.iconGroup !== group.value) || !terms.every(term => choice.dataset.iconSearch.toLowerCase().includes(term));
    });
    const count = choices.filter(choice => !choice.hidden).length;
    document.getElementById('icon-no-results').hidden = count !== 0;
    document.getElementById('icon-result-count').textContent = `${count} of ${choices.length} icons`;
  };
  const inherit = picker.querySelector('.inherit-icon');
  let activeSelect, trigger;
  const defaultIcon = () => {
    if (addCategory?.checked) return document.getElementById('id_new_category_icon').value || 'receipt';
    return categories[category?.value] || (document.getElementById('id_anchor_date') ? 'wallet' : 'receipt');
  };
  const refresh = () => document.querySelectorAll('[data-icon-target]').forEach(button => {
    const select = document.getElementById(button.dataset.iconTarget);
    const key = select.value || defaultIcon();
    const choice = choices.find(item => item.dataset.iconValue === key);
    const preview = button.querySelector('[data-icon-preview]');
    if (choice) preview.replaceChildren(choice.querySelector('svg').cloneNode(true));
    button.querySelector('[data-icon-label]').textContent = select.value ? select.selectedOptions[0].textContent : (select.id === 'id_new_category_icon' ? 'Automatic icon' : 'Use category icon');
  });
  document.querySelectorAll('[data-icon-target]').forEach(button => {
    const select = document.getElementById(button.dataset.iconTarget);
    select.hidden = true; button.hidden = false;
    select.addEventListener('change', refresh);
    button.addEventListener('click', () => {
      activeSelect = select; trigger = button;
      inherit.hidden = select.id === 'id_icon';
      inherit.textContent = select.id === 'id_new_category_icon' ? 'Automatic icon' : 'Use category icon';
      choices.forEach(choice => { choice.hidden = false; choice.setAttribute('aria-pressed', String(choice.dataset.iconValue === select.value)); });
      search.value = ''; group.value = ''; filterIcons();
      picker.showModal(); picker.querySelector(".icon-grid").scrollTop = 0; search.focus();
    });
  });
  category?.addEventListener('change', refresh); addCategory?.addEventListener('change', refresh);
  search.addEventListener('input', filterIcons);
  group.addEventListener('change', filterIcons);
  picker.querySelectorAll('[data-icon-value]').forEach(button => button.addEventListener('click', () => {
    activeSelect.value = button.dataset.iconValue;
    activeSelect.dispatchEvent(new Event('change', {bubbles:true}));
    picker.close();
  }));
  picker.querySelector('[data-close-picker]').addEventListener('click', () => picker.close());
  picker.addEventListener('close', () => trigger?.focus());
  refresh();
  if (location.hash === '#icon') document.querySelector('[data-icon-target="id_icon_override"]')?.click();
}
const filters = [...document.querySelectorAll('[data-filter]')];
filters.forEach(button => button.addEventListener('click', () => {
  filters.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  const rows = [...document.querySelectorAll('[data-type]')];
  rows.forEach(row => { row.hidden = button.dataset.filter !== 'all' && row.dataset.type !== button.dataset.filter; });
  document.getElementById('filter-empty').hidden = rows.some(row => !row.hidden);
}));
document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
  if (!window.confirm(form.dataset.confirm)) event.preventDefault();
}));
const panel = document.getElementById('complete-panel');
if (panel) {
  const initial = panel.innerHTML;
  let latestRequest = 0;
  document.querySelectorAll('[data-complete]').forEach(link => link.addEventListener('click', async event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const request = ++latestRequest;
    panel.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(link.href, {credentials:'same-origin', cache:'no-store'});
      if (!response.ok) throw new Error('Could not load completion form');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (request !== latestRequest) return;
      const form = doc.querySelector('form.form');
      const title = doc.querySelector('h1');
      if (!form || !title) throw new Error('Missing completion form');
      form.action = link.href;
      const cancel = form.querySelector('.form-actions a');
      const close = document.createElement('button');
      close.type = 'button'; close.className = 'button secondary'; close.textContent = 'Cancel';
      close.addEventListener('click', () => {
        latestRequest++; panel.innerHTML = initial;
        document.querySelectorAll('.is-selected').forEach(row => row.classList.remove('is-selected'));
        link.focus();
      });
      cancel.replaceWith(close);
      const eyebrow = document.createElement('span'); eyebrow.className = 'eyebrow'; eyebrow.textContent = 'Complete transaction';
      const row = link.closest('.transaction-row');
      const heading = document.createElement('h2'); heading.textContent = row.querySelector('.transaction-name').textContent;
      const detail = document.createElement('p'); detail.className = 'muted'; detail.textContent = (row.dataset.type === 'income' ? 'Scheduled payday ' : 'Due ') + row.querySelector('.due-date').textContent;
      const badge = document.createElement('span'); badge.className = 'large-icon'; badge.append(row.querySelector('.row-icon svg').cloneNode(true));
      panel.replaceChildren(eyebrow, badge, heading, detail, form);
      document.querySelectorAll('.is-selected').forEach(row => row.classList.remove('is-selected'));
      link.closest('.transaction-row')?.classList.add('is-selected');
      if (window.innerWidth <= 950) panel.scrollIntoView({block:'start'});
      form.querySelector('#id_amount').focus({preventScroll:window.innerWidth > 950});
    } catch (error) {
      if (request === latestRequest) location.href = link.href;
    } finally {
      if (request === latestRequest) panel.removeAttribute('aria-busy');
    }
  }));
}
