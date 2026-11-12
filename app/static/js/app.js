// Small progressive enhancement: prevent accidental double submission.
document.querySelectorAll('form').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    const button = form.querySelector('button[type="submit"],button:not([type])');
    if (button && !button.dataset.noLock) {
      button.dataset.originalText = button.textContent;
      button.disabled = true;
      button.textContent = 'Please wait…';
    }
  });
});

document.querySelectorAll('[data-order-form]').forEach((form) => {
  const tailor = form.querySelector('[data-stitch-price]');
  const design = form.querySelector('[data-design-price]');
  const output = form.querySelector('[data-order-estimate]');
  const updateEstimate = () => {
    const stitchPrice = Number(tailor.selectedOptions[0]?.dataset.price || 0);
    const designPrice = Number(design.selectedOptions[0]?.dataset.price || 0);
    output.value = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 2,
    }).format(stitchPrice + designPrice);
  };
  tailor.addEventListener('change', updateEstimate);
  design.addEventListener('change', updateEstimate);
  updateEstimate();
});
