// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyAYbCH0x7Jz8k65ljhC5cvHT7HLWahUF5A",
  authDomain: "ielts-band.firebaseapp.com",
  projectId: "ielts-band",
  storageBucket: "ielts-band.firebasestorage.app",
  messagingSenderId: "662592092440",
  appId: "1:662592092440:web:7a7bd7610603de5a8c466d",
  measurementId: "G-75J12PTY1L"
};

firebase.initializeApp(firebaseConfig);

// Cambridge IELTS 21 v3 is deliberately loaded after the main application
// script has been parsed so it can safely replace only the section-start
// routes. The renderer is independent of the legacy OCR renderer.
window.addEventListener("load", function () {
  var style = document.createElement("link");
  style.rel = "stylesheet";
  style.href = "/static/css/cambridge21-content.css?v=1";
  document.head.appendChild(style);

  var script = document.createElement("script");
  script.src = "/static/js/cambridge21-content.js?v=1";
  script.async = false;
  document.body.appendChild(script);
});
