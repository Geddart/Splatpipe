/* Shared file/directory browser for Splatpipe.
   Requires the browse modal HTML partial to be included in the page. */

var _browseTarget = null, _browseMode = 'dir', _browseCurrent = '', _browseSelected = '';

function openBrowser(targetId, mode) {
    _browseTarget = targetId; _browseMode = mode; _browseSelected = '';
    var startPath = document.getElementById(targetId).value || '';
    document.getElementById('browse-modal').showModal();
    browseNavigate(startPath);
}

function closeBrowser() {
    document.getElementById('browse-modal').close();
}

function selectBrowsed() {
    var path = _browseMode === 'file' ? _browseSelected : _browseCurrent;
    if (path && _browseTarget) document.getElementById(_browseTarget).value = path;
    closeBrowser();
}

function browseUp() {
    fetch('/settings/browse?path=' + encodeURIComponent(_browseCurrent) + '&mode=' + _browseMode)
        .then(function(r) { return r.json(); })
        .then(function(data) { browseNavigate(data.parent || ''); });
}

function browseNavigate(path) {
    _browseCurrent = path; _browseSelected = '';
    document.getElementById('browse-path-input').value = path;
    var list = document.getElementById('browse-list');
    list.innerHTML = '<div class="text-center p-4"><span class="loading loading-spinner loading-sm"></span></div>';
    fetch('/settings/browse?path=' + encodeURIComponent(path) + '&mode=' + _browseMode)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _browseCurrent = data.current || path;
            document.getElementById('browse-path-input').value = _browseCurrent;
            if (data.error) { list.innerHTML = '<div class="text-center p-4 text-error">' + data.error + '</div>'; return; }
            if (data.entries.length === 0) { list.innerHTML = '<div class="text-center p-4 opacity-60">Empty folder</div>'; return; }
            var html = '<ul class="menu menu-sm bg-base-100 w-full">';
            data.entries.forEach(function(entry) {
                var icon = entry.is_dir
                    ? '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-warning inline mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>'
                    : '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-info inline mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>';
                if (entry.is_dir) {
                    html += '<li><a onclick="browseNavigate(\'' + entry.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')">' + icon + entry.name + '</a></li>';
                } else {
                    html += '<li><a class="browse-file-entry" data-path="' + entry.path.replace(/"/g, '&quot;') + '" onclick="selectFile(this)">' + icon + entry.name + '</a></li>';
                }
            });
            list.innerHTML = html + '</ul>';
        });
}

function selectFile(el) {
    document.querySelectorAll('.browse-file-entry.active').forEach(function(a) { a.classList.remove('active'); });
    el.classList.add('active');
    _browseSelected = el.getAttribute('data-path');
}
