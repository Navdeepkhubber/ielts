(function () {
  var legacy = document.createElement('script');
  legacy.src = '/static/js/layout-view.js';
  legacy.onload = function () {
    var app = document.createElement('script');
    app.src = '/static/js/app-legacy.js';
    document.head.appendChild(app);
  };
  document.head.appendChild(legacy);
})();
