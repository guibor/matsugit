// Only Pandoc Math nodes are typeset: currency, code and ordinary text stay text.
window.MathJax = {
  tex: {
    inlineMath: [['\\(', '\\)']],
    displayMath: [['\\[', '\\]']],
    processEnvironments: false,
    processRefs: false,
    packages: {'[-]': ['autoload', 'require', 'html', 'setoptions']},
  },
  svg: {fontCache: 'none'},
  options: {
    ignoreHtmlClass: '.*',
    processHtmlClass: 'matsugit-math',
    enableMenu: false,
  },
  startup: {
    ready() {
      MathJax.startup.defaultReady();
      MathJax.startup.promise.then(() => {
        window.Reveal?.layout();
        window.dispatchEvent(new Event('resize'));
      });
    },
  },
};
