(() => {
  const form = document.getElementById('media-upload-form');
  if (!form) return;
  const input = document.getElementById('media-file');
  document.getElementById('choose-files')?.addEventListener('click', () => { input.removeAttribute('webkitdirectory'); input.click(); });
  document.getElementById('choose-folder')?.addEventListener('click', () => { input.setAttribute('webkitdirectory', ''); input.click(); });
  const zone=form.querySelector('.drop-zone');
  for (const name of ['dragenter','dragover']) zone?.addEventListener(name,event=>{event.preventDefault();zone.classList.add('is-dragging');});
  for (const name of ['dragleave','drop']) zone?.addEventListener(name,event=>{event.preventDefault();zone.classList.remove('is-dragging');if(name==='drop'&&event.dataTransfer.files.length)input.files=event.dataTransfer.files;});
  form.addEventListener('submit', event => {
    if (!form.reportValidity()) return;
    event.preventDefault();
    const progress = document.getElementById('upload-progress');
    const bar = progress.querySelector('progress');
    const label = progress.querySelector('span');
    progress.hidden = false;
    const count=input.files.length;label.textContent=`Uploading ${count} song${count===1?'':'s'}…`;
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
