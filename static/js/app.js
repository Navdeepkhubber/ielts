/* IELTS Practice Portal front-end entry point.
   The complete portal UI lives in app-legacy.js. Keep this tiny bootstrap
   so the existing UI, Firebase integration, authentication, navigation,
   scoring, and other portal behavior remain unchanged while test-content
   extraction/display is rebuilt independently. */
(function () {
  'use strict';
  var script = document.createElement('script');
  script.src = '/static/js/app-legacy.js?v=6';
  document.head.appendChild(script);
})();
