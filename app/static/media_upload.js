(() => {
  const form = document.getElementById('media-upload-form');
  if (!form) return;
  form.addEventListener('submit', event => {
    if (!form.reportValidity()) return;
    event.preventDefault();
    const progress = document.getElementById('upload-progress');
    const bar = progress.querySelector('progress');
    const label = progress.querySelector('span');
    progress.hidden = false;
    const request = new XMLHttpRequest();
    request.open('POST', form.action || location.href);
    request.upload.onprogress = event => {
      if (event.lengthComputable) {
        bar.value = Math.round(event.loaded / event.total * 100);
        label.textContent = `${bar.value}% uploaded`;
      }
    };
    request.onload = () => {
      if (request.status < 400) location.assign(request.responseURL);
      else { label.textContent = request.status === 413 ? 'File exceeds the upload limit' : 'Upload failed; try again.'; }
    };
    request.onerror = () => { label.textContent = 'Upload interrupted; try again.'; };
    request.send(new FormData(form));
  });
})();
