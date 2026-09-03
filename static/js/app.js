/* IELTS Practice Portal bootstrap.
   Load the complete legacy application first so its routes/utilities exist,
   then let the layout renderer replace the Reading/Listening start handlers. */
(function () {
  'use strict';

  var legacy = document.createElement('script');
  legacy.src = '/static/js/app-legacy.js?v=5';
  legacy.onload = function () {
    var layout = document.createElement('script');
    layout.src = '/static/js/layout-view.js?v=5';
    document.head.appendChild(layout);
  };
  document.head.appendChild(legacy);
})();
