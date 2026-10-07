(() => {
  const scope = window.FreoPage, source = document.getElementById('ad-source');
  if (!scope || !source) return;
  const update = () => document.querySelectorAll('[data-ad-fields]').forEach(node => {
    node.hidden = !node.dataset.adFields.split(' ').includes(source.value);
  });
  scope.listen(source, 'change', update); update();
})();
